"""
auto_suggest.py
Scans Ticketmaster and SeatGeek for new events matching preferences.json.
Sends email alert when a new show is found in the home region.
"""

import os
import json
import sqlite3
import datetime
import requests
from pathlib import Path
from email_sender import send_email, NOTIFY_EMAIL

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "prices.db"
PREFS_PATH = DATA_DIR / "preferences.json"

TM_KEY = os.environ.get("TICKETMASTER_KEY", "PLACEHOLDER_TM_KEY")
SG_CLIENT_ID = os.environ.get("SEATGEEK_CLIENT_ID", "PLACEHOLDER_SG_CLIENT_ID")


def init_db(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            external_id TEXT UNIQUE,
            platform TEXT,
            event_name TEXT,
            event_date TEXT,
            venue TEXT,
            url TEXT,
            first_seen TEXT
        )
    """)
    conn.commit()


def is_new(conn, external_id):
    row = conn.execute("SELECT id FROM seen_events WHERE external_id=?", (external_id,)).fetchone()
    return row is None


def mark_seen(conn, external_id, platform, name, date, venue, url):
    conn.execute(
        "INSERT OR IGNORE INTO seen_events (external_id, platform, event_name, event_date, venue, url, first_seen) VALUES (?,?,?,?,?,?,?)",
        (external_id, platform, name, date, venue, url, datetime.datetime.utcnow().isoformat())
    )
    conn.commit()


def scan_ticketmaster(keyword, region):
    results = []
    try:
        url = "https://app.ticketmaster.com/discovery/v2/events.json"
        params = {
            "apikey": TM_KEY,
            "keyword": keyword,
            "city": region,
            "size": 10,
            "startDateTime": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        for ev in data.get("_embedded", {}).get("events", []):
            dates = ev.get("dates", {}).get("start", {})
            results.append({
                "id": f"tm_{ev['id']}",
                "platform": "ticketmaster",
                "name": ev.get("name", ""),
                "date": dates.get("localDate", ""),
                "venue": ev.get("_embedded", {}).get("venues", [{}])[0].get("name", ""),
                "url": ev.get("url", ""),
            })
    except Exception as e:
        print(f"[AutoSuggest/TM] {keyword}: {e}")
    return results


def scan_seatgeek(keyword, region):
    results = []
    try:
        url = "https://api.seatgeek.com/2/events"
        params = {
            "client_id": SG_CLIENT_ID,
            "q": keyword,
            "venue.city": region,
            "per_page": 10,
        }
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        for ev in data.get("events", []):
            results.append({
                "id": f"sg_{ev['id']}",
                "platform": "seatgeek",
                "name": ev.get("title", ""),
                "date": ev.get("datetime_local", "")[:10],
                "venue": ev.get("venue", {}).get("name", ""),
                "url": ev.get("url", ""),
            })
    except Exception as e:
        print(f"[AutoSuggest/SG] {keyword}: {e}")
    return results


def send_suggest_email(new_events):
    rows = ""
    for ev in new_events:
        rows += f"""
        <tr>
          <td style="padding:10px;border-bottom:1px solid #333;">{ev['name']}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">{ev['date']}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">{ev['venue']}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">{ev['platform'].title()}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">
            <a href="{ev['url']}" style="color:#63b3ed;">View →</a>
          </td>
        </tr>"""

    html = f"""
    <html><body style="background:#1a1a2e;color:#e2e8f0;font-family:Arial,sans-serif;padding:24px;">
      <h2 style="color:#63b3ed;">🎟 TicketWatch — New Shows Found</h2>
      <p style="color:#a0aec0;">{len(new_events)} new event(s) matching your preference list</p>
      <table style="width:100%;border-collapse:collapse;margin-top:16px;">
        <thead>
          <tr style="color:#a0aec0;font-size:11px;text-transform:uppercase;">
            <th style="padding:10px;text-align:left;">Event</th>
            <th style="padding:10px;text-align:left;">Date</th>
            <th style="padding:10px;text-align:left;">Venue</th>
            <th style="padding:10px;text-align:left;">Platform</th>
            <th style="padding:10px;text-align:left;">Link</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
    </body></html>"""

    subject = f"[TicketWatch] {len(new_events)} new show(s) found for your artists/teams"
    send_email(NOTIFY_EMAIL, subject, html)
    print(f"[EMAIL] Auto-suggest alert sent: {len(new_events)} new events")


def run():
    prefs = json.loads(PREFS_PATH.read_text())
    region = prefs.get("home_region", "Washington, DC")
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    all_keywords = prefs.get("artists", []) + prefs.get("teams", [])
    new_events = []

    for keyword in all_keywords:
        print(f"[SCAN] {keyword}")
        candidates = scan_ticketmaster(keyword, region) + scan_seatgeek(keyword, region)

        for ev in candidates:
            if is_new(conn, ev["id"]):
                print(f"  [NEW] {ev['name']} — {ev['date']} @ {ev['venue']}")
                new_events.append(ev)
                mark_seen(conn, ev["id"], ev["platform"], ev["name"], ev["date"], ev["venue"], ev["url"])

    conn.close()

    if new_events:
        send_suggest_email(new_events)
    else:
        print("[DONE] No new events found.")


if __name__ == "__main__":
    run()
