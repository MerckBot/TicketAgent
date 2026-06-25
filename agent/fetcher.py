"""
fetcher.py
Queries Ticketmaster, StubHub, and SeatGeek for each event in events.json.
Writes price snapshots to SQLite. Skips events not due for a check yet.
"""

import os
import json
import sqlite3
import datetime
import requests
from pathlib import Path
from token_manager import get_stubhub_token

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "prices.db"
EVENTS_PATH = DATA_DIR / "events.json"

TM_KEY = os.environ.get("TICKETMASTER_KEY", "PLACEHOLDER_TM_KEY")
SG_CLIENT_ID = os.environ.get("SEATGEEK_CLIENT_ID", "PLACEHOLDER_SG_CLIENT_ID")


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
    conn.commit()
    return conn


# ── Check frequency logic ─────────────────────────────────────────────────────

def is_due_for_check(event_date_str):
    """Return True if this event is due for a price check based on proximity."""
    today = datetime.date.today()
    try:
        event_date = datetime.date.fromisoformat(event_date_str)
    except ValueError:
        return False

    days_until = (event_date - today).days
    if days_until < 0:
        return False  # Past event

    now_hour = datetime.datetime.utcnow().hour

    if days_until > 30:
        # Weekly — check on Mondays
        return datetime.datetime.utcnow().weekday() == 0 and now_hour == 0
    elif days_until > 7:
        # Daily — check at midnight UTC
        return now_hour == 0
    elif days_until > 1:
        # Every 6 hours
        return now_hour % 6 == 0
    else:
        # Day-of — every 2 hours
        return now_hour % 2 == 0


# ── Platform fetchers ─────────────────────────────────────────────────────────

def fetch_ticketmaster(event):
    """Query Ticketmaster Discovery API."""
    try:
        url = "https://app.ticketmaster.com/discovery/v2/events.json"
        params = {
            "apikey": TM_KEY,
            "keyword": event["event"],
            "city": event.get("city", ""),
            "startDateTime": f"{event['date']}T00:00:00Z",
            "endDateTime": f"{event['date']}T23:59:59Z",
            "size": 5,
        }
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        events = data.get("_embedded", {}).get("events", [])
        if not events:
            return None

        # Find cheapest price range across results
        best = None
        best_url = None
        for ev in events:
            price_ranges = ev.get("priceRanges", [])
            for pr in price_ranges:
                min_price = pr.get("min")
                if min_price and (best is None or min_price < best):
                    best = min_price
                    best_url = ev.get("url")

        if best:
            return {"platform": "ticketmaster", "lowest_price": best, "section": "General", "quantity": None, "url": best_url}
    except Exception as e:
        print(f"[Ticketmaster] Error: {e}")
    return None


def fetch_stubhub(event):
    """Query StubHub API v3."""
    try:
        token = get_stubhub_token()
        url = "https://api.stubhub.com/sellers/search/events/v3"
        params = {"name": event["event"], "city": event.get("city", "")}
        r = requests.get(url, headers={"Authorization": f"Bearer {token}"}, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        items = data.get("events", [])
        if not items:
            return None

        best = None
        best_url = None
        for item in items:
            price = item.get("minPrice") or item.get("ticketInfo", {}).get("minPrice")
            if price and (best is None or price < best):
                best = price
                best_url = f"https://www.stubhub.com/event/{item.get('id', '')}"

        if best:
            return {"platform": "stubhub", "lowest_price": best, "section": "General", "quantity": None, "url": best_url}
    except Exception as e:
        print(f"[StubHub] Error: {e}")
    return None


def fetch_seatgeek(event):
    """Query SeatGeek API."""
    try:
        url = "https://api.seatgeek.com/2/events"
        params = {
            "client_id": SG_CLIENT_ID,
            "q": event["event"],
            "venue.city": event.get("city", ""),
            "datetime_local.gte": f"{event['date']}T00:00:00",
            "datetime_local.lte": f"{event['date']}T23:59:59",
            "per_page": 5,
        }
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        items = data.get("events", [])
        if not items:
            return None

        best = None
        best_url = None
        for item in items:
            stats = item.get("stats", {})
            price = stats.get("lowest_price")
            if price and (best is None or price < best):
                best = price
                best_url = item.get("url")

        if best:
            return {"platform": "seatgeek", "lowest_price": best, "section": "General", "quantity": None, "url": best_url}
    except Exception as e:
        print(f"[SeatGeek] Error: {e}")
    return None


# ── Main ──────────────────────────────────────────────────────────────────────

def run():
    conn = init_db()
    events = json.loads(EVENTS_PATH.read_text())
    now = datetime.datetime.utcnow().isoformat()

    for event in events:
        if not is_due_for_check(event["date"]):
            print(f"[SKIP] {event['event']} — not due for check")
            continue

        print(f"\n[CHECK] {event['event']} on {event['date']}")
        results = []

        for fetcher in [fetch_ticketmaster, fetch_stubhub, fetch_seatgeek]:
            result = fetcher(event)
            if result:
                results.append(result)
                conn.execute(
                    "INSERT INTO price_history (event_id, platform, checked_at, lowest_price, section, quantity_available, listing_url) VALUES (?,?,?,?,?,?,?)",
                    (event["id"], result["platform"], now, result["lowest_price"], result.get("section"), result.get("quantity"), result.get("url"))
                )
                print(f"  [{result['platform'].upper()}] ${result['lowest_price']:.2f}")
            else:
                print(f"  [{fetcher.__name__.replace('fetch_','')}] No results")

        conn.commit()

        # Pass results to alert engine
        from alert_engine import evaluate_triggers
        evaluate_triggers(event, results, conn, now)

    conn.close()
    print("\n[DONE] Price check complete.")


if __name__ == "__main__":
    run()
