"""
auto_suggest.py (v1.2)
Scans Ticketmaster and SeatGeek for new events matching preferences.json.
Sends an email alert when a new show is found in the home region.

v1.2 changes:
- First run auto-seeds: everything found is marked seen WITHOUT emailing,
  so you don't get a 100-row "new events" blast on day one. (--seed forces
  this behavior on demand.)
- City/state are split properly for both APIs ("Washington, DC" was likely
  matching nothing).
- SeatGeek scan now has a date floor (no past events).
- New-event rows only marked seen if the alert email succeeds.
"""

import os
import json
import sqlite3
import argparse
import datetime
from datetime import timezone
from pathlib import Path

import requests

from email_sender import send_email, esc, NOTIFY_EMAIL

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "prices.db"
PREFS_PATH = DATA_DIR / "preferences.json"

TM_KEY = os.environ.get("TICKETMASTER_KEY", "")
SG_CLIENT_ID = os.environ.get("SEATGEEK_CLIENT_ID", "")

# SeatGeek returns 403 to the default `python-requests/x.x` User-Agent from
# GitHub Actions' IPs; a browser-like UA is a cheap thing to rule out before
# assuming it's a hard IP/ASN block.
SEATGEEK_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"),
    "Accept": "application/json",
}


def creds_present(value):
    return bool(value) and not value.startswith("PLACEHOLDER")


def split_city_state(city_field):
    if not city_field:
        return "", ""
    parts = [p.strip() for p in city_field.split(",")]
    if len(parts) >= 2 and len(parts[-1]) == 2:
        return ", ".join(parts[:-1]), parts[-1].upper()
    return city_field.strip(), ""


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
    row = conn.execute("SELECT id FROM seen_events WHERE external_id=?",
                       (external_id,)).fetchone()
    return row is None


def mark_seen(conn, ev):
    conn.execute(
        "INSERT OR IGNORE INTO seen_events (external_id, platform, event_name, "
        "event_date, venue, url, first_seen) VALUES (?,?,?,?,?,?,?)",
        (ev["id"], ev["platform"], ev["name"], ev["date"], ev["venue"],
         ev["url"], datetime.datetime.now(timezone.utc).isoformat())
    )


def scan_ticketmaster(keyword, city, state):
    if not creds_present(TM_KEY):
        print("  [TM] Skipped — credentials not configured yet")
        return []
    results = []
    try:
        url = "https://app.ticketmaster.com/discovery/v2/events.json"
        params = {
            "apikey": TM_KEY,
            "keyword": keyword,
            "size": 10,
            "startDateTime": datetime.datetime.now(timezone.utc)
                             .strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if city:
            params["city"] = city
        if state:
            params["stateCode"] = state
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        for ev in data.get("_embedded", {}).get("events", []):
            dates = ev.get("dates", {}).get("start", {})
            venues = ev.get("_embedded", {}).get("venues", [{}])
            results.append({
                "id": f"tm_{ev['id']}",
                "platform": "ticketmaster",
                "name": ev.get("name") or "",
                "date": dates.get("localDate") or "",
                "venue": (venues[0] if venues else {}).get("name") or "",
                "url": ev.get("url") or "",
            })
    except Exception as e:
        print(f"[AutoSuggest/TM] {keyword}: {e}")
    return results


def scan_seatgeek(keyword, city, state):
    if not creds_present(SG_CLIENT_ID):
        print("  [SG] Skipped — credentials not configured yet")
        return []
    results = []
    try:
        url = "https://api.seatgeek.com/2/events"
        params = {
            "client_id": SG_CLIENT_ID,
            "q": keyword,
            "per_page": 10,
            "datetime_utc.gte": datetime.datetime.now(timezone.utc)
                                .strftime("%Y-%m-%dT%H:%M:%S"),
        }
        if city:
            params["venue.city"] = city
        if state:
            params["venue.state"] = state
        r = requests.get(url, params=params, headers=SEATGEEK_HEADERS, timeout=10)
        r.raise_for_status()
        data = r.json()
        for ev in data.get("events", []):
            results.append({
                "id": f"sg_{ev['id']}",
                "platform": "seatgeek",
                "name": ev.get("title") or "",
                "date": (ev.get("datetime_local") or "")[:10],
                "venue": (ev.get("venue") or {}).get("name") or "",
                "url": ev.get("url") or "",
            })
    except Exception as e:
        print(f"[AutoSuggest/SG] {keyword}: {e}")
    return results


def send_suggest_email(new_events):
    rows = ""
    for ev in new_events:
        rows += f"""
        <tr>
          <td style="padding:10px;border-bottom:1px solid #333;">{esc(ev['name'])}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">{esc(ev['date'])}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">{esc(ev['venue'])}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">{esc(ev['platform'].title())}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">
            <a href="{esc(ev['url'])}" style="color:#63b3ed;">View →</a>
          </td>
        </tr>"""

    html_body = f"""
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
    return send_email(NOTIFY_EMAIL, subject, html_body)


def run(seed=False):
    prefs = json.loads(PREFS_PATH.read_text())
    region = prefs.get("home_region", "Washington, DC")
    city, state = split_city_state(region)

    conn = sqlite3.connect(DB_PATH)
    init_db(conn)

    # First run ever? Seed silently instead of emailing everything as "new".
    if not seed:
        count = conn.execute("SELECT COUNT(*) FROM seen_events").fetchone()[0]
        if count == 0:
            print("[SEED] seen_events is empty — seeding baseline, no email this run")
            seed = True

    all_keywords = prefs.get("artists", []) + prefs.get("teams", [])
    new_events = []
    seen_this_run = set()   # same event can match multiple keywords

    for keyword in all_keywords:
        print(f"[SCAN] {keyword}")
        candidates = (scan_ticketmaster(keyword, city, state)
                      + scan_seatgeek(keyword, city, state))
        for ev in candidates:
            if ev["id"] in seen_this_run:
                continue
            seen_this_run.add(ev["id"])
            if is_new(conn, ev["id"]):
                print(f"  [NEW] {ev['name']} — {ev['date']} @ {ev['venue']}")
                new_events.append(ev)

    if not new_events:
        print("[DONE] No new events found.")
    elif seed:
        for ev in new_events:
            mark_seen(conn, ev)
        conn.commit()
        print(f"[SEED] Baseline stored: {len(new_events)} events. "
              f"Future runs alert only on genuinely new shows.")
    else:
        # Only mark seen if the email went out — otherwise retry tomorrow
        if send_suggest_email(new_events):
            for ev in new_events:
                mark_seen(conn, ev)
            conn.commit()
            print(f"[EMAIL] Auto-suggest alert sent: {len(new_events)} new events")
        else:
            print("[WARN] Alert email failed — events NOT marked seen, "
                  "will retry next run")

    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", action="store_true",
                        help="Mark all current results as seen without emailing")
    args = parser.parse_args()
    run(seed=args.seed)
