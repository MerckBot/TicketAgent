"""
fetcher.py (v1.2)
Queries StubHub and SeatGeek for each event in events.json.
Ticketmaster is NOT a price source (Discovery API returns static face-value
ranges, not live prices) — it is used only by auto_suggest.py for discovery.

Writes price snapshots to SQLite. Uses per-(event, platform) last_checked
timestamps, so delayed/skipped GitHub cron runs never silently drop a check,
and StubHub (cloud) and SeatGeek (self-hosted, see README) can run on
independent schedules without one platform's run starving the other's.
"""

import os
import json
import sqlite3
import argparse
import datetime
from datetime import timezone
from pathlib import Path

import requests

from token_manager import get_stubhub_token, stubhub_creds_present

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "prices.db"
EVENTS_PATH = DATA_DIR / "events.json"

SG_CLIENT_ID = os.environ.get("SEATGEEK_CLIENT_ID", "")

# SeatGeek 403s every request from GitHub Actions' IPs specifically (confirmed
# 2026-07-06), including through a rotating-IP proxy (ScraperAPI, ruled out
# 2026-07-11) — it's an IP/ASN-level block. A self-hosted runner on a
# residential IP works fine, so SeatGeek runs there instead (see README).
SEATGEEK_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}


def creds_present(value):
    return bool(value) and not value.startswith("PLACEHOLDER")


def utcnow():
    return datetime.datetime.now(timezone.utc)


def split_city_state(city_field):
    """'Las Vegas, NV' -> ('Las Vegas', 'NV'); 'Las Vegas' -> ('Las Vegas', '')."""
    if not city_field:
        return "", ""
    parts = [p.strip() for p in city_field.split(",")]
    if len(parts) >= 2 and len(parts[-1]) == 2:
        return ", ".join(parts[:-1]), parts[-1].upper()
    return city_field.strip(), ""


# ── DB setup ──────────────────────────────────────────────────────────────────

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT,
            platform TEXT,
            checked_at TEXT,
            lowest_price REAL,
            section TEXT,
            quantity_available INTEGER,
            listing_url TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS alert_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT,
            platform TEXT,
            trigger_type TEXT,
            price REAL,
            fired_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS platform_state (
            event_id TEXT,
            platform TEXT,
            last_checked TEXT,
            PRIMARY KEY (event_id, platform)
        )
    """)
    conn.execute("DROP TABLE IF EXISTS event_state")  # superseded by platform_state
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_price_history_lookup
        ON price_history (event_id, platform, checked_at)
    """)
    conn.commit()
    return conn


# ── Check frequency logic ─────────────────────────────────────────────────────

def required_interval_hours(days_until):
    """How often an event should be checked, by proximity."""
    if days_until > 30:
        return 168   # weekly
    if days_until > 7:
        return 24    # daily
    if days_until > 1:
        return 6
    return 2         # day before + day of (+1 day grace for UTC/local skew)


def event_days_until(event, now):
    """Days from now to the event date, or None if the date is unparseable."""
    date_str = event.get("date", "")
    try:
        event_date = datetime.date.fromisoformat(date_str)
    except (ValueError, TypeError):
        return None
    return (event_date - now.date()).days


def is_platform_due(event, platform, days_until, conn, now):
    """Elapsed-time check against platform_state.last_checked for one platform.

    Tracked per (event, platform) rather than per event, so StubHub (cloud,
    hourly) and SeatGeek (self-hosted, only when that runner is online) can
    each follow their own cadence without one starving the other's check.
    """
    row = conn.execute(
        "SELECT last_checked FROM platform_state WHERE event_id=? AND platform=?",
        (event["id"], platform)
    ).fetchone()
    if not row or not row[0]:
        return True

    last = datetime.datetime.fromisoformat(row[0])
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed_hours = (now - last).total_seconds() / 3600.0

    # 0.25h tolerance so a cron run landing a few minutes early still counts
    return elapsed_hours >= required_interval_hours(days_until) - 0.25


def mark_checked(conn, event_id, platform, now_iso):
    conn.execute(
        "INSERT INTO platform_state (event_id, platform, last_checked) VALUES (?, ?, ?) "
        "ON CONFLICT(event_id, platform) DO UPDATE SET last_checked=excluded.last_checked",
        (event_id, platform, now_iso)
    )
    conn.commit()


# ── Platform fetchers ─────────────────────────────────────────────────────────

def fetch_stubhub(event):
    """Query StubHub API. Skips cleanly if credentials aren't configured."""
    if not stubhub_creds_present():
        print("  [STUBHUB] Skipped — credentials not configured yet")
        return None
    try:
        token = get_stubhub_token()
        url = "https://api.stubhub.com/sellers/search/events/v3"
        city, _state = split_city_state(event.get("city", ""))
        params = {"name": event["event"], "city": city}
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"},
                         params=params, timeout=10)
        r.raise_for_status()
        items = r.json().get("events", [])
        if not items:
            return None

        best = None
        best_url = None
        for item in items:
            price = item.get("minPrice")
            if price is None:
                price = item.get("ticketInfo", {}).get("minPrice")
            try:
                price = float(price) if price is not None else None
            except (TypeError, ValueError):
                continue
            if price is not None and (best is None or price < best):
                best = price
                best_url = f"https://www.stubhub.com/event/{item.get('id', '')}"

        if best is not None:
            return {"platform": "stubhub", "lowest_price": best,
                    "section": "General", "quantity": None, "url": best_url}
    except Exception as e:
        print(f"  [STUBHUB] Error: {e}")
    return None


def fetch_seatgeek(event):
    """Query SeatGeek API. Skips cleanly if credentials aren't configured."""
    if not creds_present(SG_CLIENT_ID):
        print("  [SEATGEEK] Skipped — credentials not configured yet")
        return None
    try:
        url = "https://api.seatgeek.com/2/events"
        city, state = split_city_state(event.get("city", ""))
        params = {
            "client_id": SG_CLIENT_ID,
            "q": event["event"],
            "datetime_local.gte": f"{event['date']}T00:00:00",
            "datetime_local.lte": f"{event['date']}T23:59:59",
            "per_page": 5,
        }
        if city:
            params["venue.city"] = city
        if state:
            params["venue.state"] = state
        r = requests.get(url, params=params, headers=SEATGEEK_HEADERS, timeout=10)
        r.raise_for_status()
        items = r.json().get("events", [])
        if not items:
            return None

        best = None
        best_url = None
        for item in items:
            price = (item.get("stats") or {}).get("lowest_price")
            try:
                price = float(price) if price is not None else None
            except (TypeError, ValueError):
                continue
            if price is not None and (best is None or price < best):
                best = price
                best_url = item.get("url")

        if best is not None:
            return {"platform": "seatgeek", "lowest_price": best,
                    "section": "General", "quantity": None, "url": best_url}
    except Exception as e:
        print(f"  [SEATGEEK] Error: {e}")
    return None


PRICE_FETCHERS = [("stubhub", fetch_stubhub), ("seatgeek", fetch_seatgeek)]


# ── Main ──────────────────────────────────────────────────────────────────────

def run(platforms=None):
    """platforms: optional set restricting which fetchers run (default: all)."""
    from alert_engine import evaluate_triggers

    conn = init_db()
    events = json.loads(EVENTS_PATH.read_text())

    # Fail loudly on duplicate IDs instead of silently corrupting history
    ids = [e.get("id") for e in events]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise SystemExit(f"[FATAL] Duplicate event ids in events.json: {sorted(dupes)}")

    now = utcnow()
    now_iso = now.isoformat()
    fetchers = [(name, fn) for name, fn in PRICE_FETCHERS
                if platforms is None or name in platforms]

    for event in events:
        days_until = event_days_until(event, now)
        if days_until is None:
            print(f"  [WARN] {event.get('id','?')} '{event.get('event','?')}' has "
                  f"unparseable date '{event.get('date','')}' — skipping until a real date is set.")
            continue
        # Runner clock is UTC; a US evening event is still live when UTC has
        # rolled to the next day, so keep checking through days_until == -1.
        if days_until < -1:
            continue

        due = [(name, fn) for name, fn in fetchers
               if is_platform_due(event, name, days_until, conn, now)]
        if not due:
            print(f"[SKIP] {event.get('event','?')} — no platforms due for check")
            continue

        print(f"\n[CHECK] {event['event']} on {event['date']}")
        results = []

        for platform_name, fetcher in due:
            result = fetcher(event)
            if result:
                results.append(result)
                conn.execute(
                    "INSERT INTO price_history (event_id, platform, checked_at, "
                    "lowest_price, section, quantity_available, listing_url) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (event["id"], result["platform"], now_iso,
                     result["lowest_price"], result.get("section"),
                     result.get("quantity"), result.get("url"))
                )
                print(f"  [{result['platform'].upper()}] ${result['lowest_price']:.2f}")
            mark_checked(conn, event["id"], platform_name, now_iso)
        conn.commit()

        evaluate_triggers(event, results, conn, now_iso)

    conn.close()
    print("\n[DONE] Price check complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--platforms", help="Comma-separated platform list "
                         "(stubhub,seatgeek). Default: all.")
    args = parser.parse_args()
    run(platforms=set(args.platforms.split(",")) if args.platforms else None)
