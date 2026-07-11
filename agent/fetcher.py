"""
fetcher.py (v1.2)
Queries StubHub and SeatGeek for each event in events.json.
Ticketmaster is NOT a price source (Discovery API returns static face-value
ranges, not live prices) — it is used only by auto_suggest.py for discovery.

Writes price snapshots to SQLite. Uses per-event last_checked timestamps,
so delayed/skipped GitHub cron runs never silently drop a check.
"""

import os
import json
import sqlite3
import datetime
from datetime import timezone
from pathlib import Path
from urllib.parse import urlencode

import requests

from token_manager import get_stubhub_token, stubhub_creds_present

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "prices.db"
EVENTS_PATH = DATA_DIR / "events.json"

SG_CLIENT_ID = os.environ.get("SEATGEEK_CLIENT_ID", "")
SCRAPERAPI_KEY = os.environ.get("SCRAPERAPI_KEY", "")

# A browser-like UA didn't fix SeatGeek's 403 from GitHub Actions (confirmed
# 2026-07-11) — it's an IP/ASN-level block, not a bot-signature check. Kept
# anyway since it's harmless. SCRAPERAPI_KEY routes the request through
# ScraperAPI's free-tier proxy (rotating IPs) to get around the block.
SEATGEEK_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}


def creds_present(value):
    return bool(value) and not value.startswith("PLACEHOLDER")


def seatgeek_get(url, params, timeout=20):
    """GET a SeatGeek endpoint, routed through ScraperAPI if configured.

    SeatGeek 403s every request from GitHub Actions' IPs directly (confirmed
    2026-07-11), so when SCRAPERAPI_KEY is set we tunnel through ScraperAPI's
    rotating-IP proxy instead of hitting SeatGeek directly.
    """
    if creds_present(SCRAPERAPI_KEY):
        target = f"{url}?{urlencode(params)}"
        return requests.get(
            "https://api.scraperapi.com",
            params={"api_key": SCRAPERAPI_KEY, "url": target},
            timeout=timeout + 20,  # ScraperAPI adds proxy/retry latency
        )
    return requests.get(url, params=params, headers=SEATGEEK_HEADERS, timeout=timeout)


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
        CREATE TABLE IF NOT EXISTS event_state (
            event_id TEXT PRIMARY KEY,
            last_checked TEXT
        )
    """)
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


def is_due_for_check(event, conn, now):
    """Elapsed-time check against event_state.last_checked.

    Robust against GitHub's delayed/skipped cron runs: a missed hour just
    means the next run picks it up, instead of losing a whole day or week.
    """
    date_str = event.get("date", "")
    try:
        event_date = datetime.date.fromisoformat(date_str)
    except (ValueError, TypeError):
        print(f"  [WARN] {event.get('id','?')} '{event.get('event','?')}' has "
              f"unparseable date '{date_str}' — skipping until a real date is set.")
        return False

    days_until = (event_date - now.date()).days
    # Runner clock is UTC; a US evening event is still live when UTC has
    # rolled to the next day, so keep checking through days_until == -1.
    if days_until < -1:
        return False

    row = conn.execute(
        "SELECT last_checked FROM event_state WHERE event_id=?", (event["id"],)
    ).fetchone()
    if not row or not row[0]:
        return True

    last = datetime.datetime.fromisoformat(row[0])
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    elapsed_hours = (now - last).total_seconds() / 3600.0

    # 0.25h tolerance so a cron run landing a few minutes early still counts
    return elapsed_hours >= required_interval_hours(days_until) - 0.25


def mark_checked(conn, event_id, now_iso):
    conn.execute(
        "INSERT INTO event_state (event_id, last_checked) VALUES (?, ?) "
        "ON CONFLICT(event_id) DO UPDATE SET last_checked=excluded.last_checked",
        (event_id, now_iso)
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
        r = seatgeek_get(url, params, timeout=10)
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


PRICE_FETCHERS = [fetch_stubhub, fetch_seatgeek]


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
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

    for event in events:
        if not is_due_for_check(event, conn, now):
            print(f"[SKIP] {event.get('event','?')} — not due for check")
            continue

        print(f"\n[CHECK] {event['event']} on {event['date']}")
        results = []

        for fetcher in PRICE_FETCHERS:
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
        conn.commit()

        evaluate_triggers(event, results, conn, now_iso)
        mark_checked(conn, event["id"], now_iso)

    conn.close()
    print("\n[DONE] Price check complete.")


if __name__ == "__main__":
    run()
