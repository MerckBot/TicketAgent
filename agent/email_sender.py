"""
email_sender.py
Sends alert emails and weekly digest via SendGrid or SMTP fallback.
Usage:
  from email_sender import send_alert_email
  python email_sender.py --mode digest
"""

import os
import json
import sqlite3
import argparse
import datetime
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "prices.db"
NOTIFY_PATH = DATA_DIR / "notify.json"
EVENTS_PATH = DATA_DIR / "events.json"

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "jmerck2d2@gmail.com")


def load_notify():
    return json.loads(NOTIFY_PATH.read_text())


# ── Transport ─────────────────────────────────────────────────────────────────

def send_email(to_addr, subject, html_body):
    """Send via SendGrid if key present, else SMTP."""
    if SENDGRID_API_KEY and SENDGRID_API_KEY != "PLACEHOLDER_SENDGRID_KEY":
        _send_via_sendgrid(to_addr, subject, html_body)
    else:
        _send_via_smtp(to_addr, subject, html_body)


def _send_via_sendgrid(to_addr, subject, html_body):
    import urllib.request
    payload = json.dumps({
        "personalizations": [{"to": [{"email": to_addr}]}],
        "from": {"email": "ticketwatch@noreply.com"},
        "subject": subject,
        "content": [{"type": "text/html", "value": html_body}],
    }).encode()
    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=payload,
        headers={
            "Authorization": f"Bearer {SENDGRID_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        print(f"[SendGrid] Status: {resp.status}")


def _send_via_smtp(to_addr, subject, html_body):
    cfg = load_notify()
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = smtp_user or "ticketwatch@gmail.com"
    msg["To"] = to_addr
    msg.attach(MIMEText(html_body, "html"))

    with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"]) as server:
        server.starttls()
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        server.sendmail(msg["From"], to_addr, msg.as_string())
    print(f"[SMTP] Sent to {to_addr}")


# ── Alert email ───────────────────────────────────────────────────────────────

def send_alert_email(event, triggers):
    subject_parts = list({t["trigger"] for t in triggers})
    label = " + ".join(t.replace("_", " ") for t in subject_parts)
    subject = f"[TicketWatch] {event['event']} — {label}"

    rows = ""
    for t in triggers:
        badge_color = "#e53e3e" if t["trigger"] == "PRICE_ALERT" else "#2b6cb0"
        prev = f" (was ${t['prev_price']:.2f})" if "prev_price" in t else ""
        rows += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #333;">
            <span style="background:{badge_color};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;">{t['trigger'].replace('_',' ')}</span>
          </td>
          <td style="padding:8px;border-bottom:1px solid #333;">{t['platform'].title()}</td>
          <td style="padding:8px;border-bottom:1px solid #333;"><strong>${t['price']:.2f}</strong>{prev}</td>
          <td style="padding:8px;border-bottom:1px solid #333;">
            <a href="{t.get('url','#')}" style="color:#63b3ed;">View Listing →</a>
          </td>
        </tr>"""

    html = f"""
    <html><body style="background:#1a1a2e;color:#e2e8f0;font-family:Arial,sans-serif;padding:24px;">
      <h2 style="color:#63b3ed;">🎟 TicketWatch Alert</h2>
      <p><strong>{event['event']}</strong><br>
         {event.get('venue','')} &bull; {event['date']} &bull; {event.get('city','')}</p>
      <table style="width:100%;border-collapse:collapse;margin-top:16px;">
        <thead>
          <tr style="color:#a0aec0;font-size:12px;text-transform:uppercase;">
            <th style="padding:8px;text-align:left;">Trigger</th>
            <th style="padding:8px;text-align:left;">Platform</th>
            <th style="padding:8px;text-align:left;">Price</th>
            <th style="padding:8px;text-align:left;">Link</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="margin-top:16px;color:#a0aec0;font-size:12px;">
        Your target: ${event.get('max_price','—')} &bull; Qty needed: {event.get('quantity','—')}<br>
        Next check scheduled automatically.
      </p>
    </body></html>"""

    send_email(NOTIFY_EMAIL, subject, html)
    print(f"[EMAIL] Alert sent: {subject}")


# ── Weekly digest ─────────────────────────────────────────────────────────────

def send_digest():
    conn = sqlite3.connect(DB_PATH)
    events = json.loads(EVENTS_PATH.read_text())
    today = datetime.date.today()
    last_week = (datetime.datetime.utcnow() - datetime.timedelta(days=7)).isoformat()

    rows = ""
    for event in events:
        if not event.get("digest", True):
            continue

        try:
            event_date = datetime.date.fromisoformat(event["date"])
            days_until = (event_date - today).days
        except ValueError:
            days_until = "?"

        # Get current lows per platform
        platforms = {}
        for platform in ["ticketmaster", "stubhub", "seatgeek"]:
            row = conn.execute(
                "SELECT lowest_price FROM price_history WHERE event_id=? AND platform=? ORDER BY checked_at DESC LIMIT 1",
                (event["id"], platform)
            ).fetchone()
            platforms[platform] = f"${row[0]:.2f}" if row else "—"

        # Price trend vs last week
        trend_rows = conn.execute(
            "SELECT lowest_price FROM price_history WHERE event_id=? ORDER BY checked_at DESC LIMIT 2",
            (event["id"],)
        ).fetchall()
        if len(trend_rows) >= 2:
            diff = trend_rows[0][0] - trend_rows[1][0]
            trend = "↓" if diff < 0 else ("↑" if diff > 0 else "→")
            trend_color = "#48bb78" if diff < 0 else ("#fc8181" if diff > 0 else "#a0aec0")
        else:
            trend = "—"
            trend_color = "#a0aec0"

        rows += f"""
        <tr>
          <td style="padding:10px;border-bottom:1px solid #333;">{event['event']}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">{event['date']}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">{days_until}d</td>
          <td style="padding:10px;border-bottom:1px solid #333;">{platforms['ticketmaster']}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">{platforms['stubhub']}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">{platforms['seatgeek']}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">${event.get('max_price','—')}</td>
          <td style="padding:10px;border-bottom:1px solid #333;color:{trend_color};font-size:18px;">{trend}</td>
        </tr>"""

    conn.close()

    subject = f"[TicketWatch Weekly] {len(events)} events tracked — {today.strftime('%b %d, %Y')}"
    html = f"""
    <html><body style="background:#1a1a2e;color:#e2e8f0;font-family:Arial,sans-serif;padding:24px;">
      <h2 style="color:#63b3ed;">🎟 TicketWatch Weekly Digest</h2>
      <p style="color:#a0aec0;">{today.strftime('%A, %B %d, %Y')}</p>
      <table style="width:100%;border-collapse:collapse;margin-top:16px;">
        <thead>
          <tr style="color:#a0aec0;font-size:11px;text-transform:uppercase;">
            <th style="padding:10px;text-align:left;">Event</th>
            <th style="padding:10px;text-align:left;">Date</th>
            <th style="padding:10px;text-align:left;">Days Out</th>
            <th style="padding:10px;text-align:left;">TM Low</th>
            <th style="padding:10px;text-align:left;">StubHub Low</th>
            <th style="padding:10px;text-align:left;">SeatGeek Low</th>
            <th style="padding:10px;text-align:left;">Your Target</th>
            <th style="padding:10px;text-align:left;">Trend</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="margin-top:24px;color:#a0aec0;font-size:12px;">
        Sent by TicketWatch &bull; {datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}
      </p>
    </body></html>"""

    send_email(NOTIFY_EMAIL, subject, html)
    print(f"[EMAIL] Digest sent to {NOTIFY_EMAIL}")


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["digest"], required=True)
    args = parser.parse_args()
    if args.mode == "digest":
        send_digest()
