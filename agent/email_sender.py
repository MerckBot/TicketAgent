"""
email_sender.py (v1.2)
Sends alert emails and weekly digest via SendGrid, with SMTP fallback.

v1.2 changes:
- SendGrid "from" comes from the SENDGRID_FROM secret (must be a verified
  sender in your SendGrid account) — the old hardcoded ticketwatch@noreply.com
  was guaranteed a 403.
- send_email() returns True/False and never raises; SendGrid failure falls
  back to SMTP instead of crashing the whole run.
- Digest trend now compares like-for-like: this week's low vs the low from
  >= 7 days ago, per event across StubHub/SeatGeek.
- Ticketmaster column removed (no longer a price source).
- All API-sourced strings are HTML-escaped.
"""

import os
import html
import json
import sqlite3
import argparse
import datetime
import smtplib
from datetime import timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
DB_PATH = DATA_DIR / "prices.db"
NOTIFY_PATH = DATA_DIR / "notify.json"
EVENTS_PATH = DATA_DIR / "events.json"

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY", "")
SENDGRID_FROM = os.environ.get("SENDGRID_FROM", "")
NOTIFY_EMAIL = os.environ.get("NOTIFY_EMAIL", "jmerck2d2@gmail.com")

PRICE_PLATFORMS = ["stubhub", "seatgeek"]


def esc(value):
    return html.escape(str(value)) if value is not None else ""


def load_notify():
    return json.loads(NOTIFY_PATH.read_text())


# ── Transport ─────────────────────────────────────────────────────────────────

def send_email(to_addr, subject, html_body):
    """Try SendGrid, fall back to SMTP. Returns True on success."""
    if SENDGRID_API_KEY and SENDGRID_FROM:
        if _send_via_sendgrid(to_addr, subject, html_body):
            return True
        print("[EMAIL] SendGrid failed — trying SMTP fallback")
    return _send_via_smtp(to_addr, subject, html_body)


def _send_via_sendgrid(to_addr, subject, html_body):
    import urllib.request
    import urllib.error
    payload = json.dumps({
        "personalizations": [{"to": [{"email": to_addr}]}],
        "from": {"email": SENDGRID_FROM},
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
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"[SendGrid] Status: {resp.status}")
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode()[:300]
        except Exception:
            pass
        print(f"[SendGrid] HTTP {e.code}: {body}")
    except Exception as e:
        print(f"[SendGrid] Error: {e}")
    return False


def _send_via_smtp(to_addr, subject, html_body):
    smtp_user = os.environ.get("SMTP_USER", "")
    smtp_pass = os.environ.get("SMTP_PASS", "")
    if not (smtp_user and smtp_pass):
        print("[SMTP] Skipped — SMTP_USER/SMTP_PASS not configured")
        return False

    try:
        cfg = load_notify()
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = smtp_user
        msg["To"] = to_addr
        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP(cfg["smtp_host"], cfg["smtp_port"], timeout=15) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(msg["From"], to_addr, msg.as_string())
        print(f"[SMTP] Sent to {to_addr}")
        return True
    except Exception as e:
        print(f"[SMTP] Error: {e}")
        return False


# ── Alert email ───────────────────────────────────────────────────────────────

def send_alert_email(event, triggers):
    """Returns True if the email was actually delivered to the transport."""
    subject_parts = sorted({t["trigger"] for t in triggers})
    label = " + ".join(t.replace("_", " ") for t in subject_parts)
    subject = f"[TicketWatch] {event['event']} — {label}"

    rows = ""
    for t in triggers:
        badge_color = "#e53e3e" if t["trigger"] == "PRICE_ALERT" else "#2b6cb0"
        prev = f" (was ${t['prev_price']:.2f})" if "prev_price" in t else ""
        rows += f"""
        <tr>
          <td style="padding:8px;border-bottom:1px solid #333;">
            <span style="background:{badge_color};color:#fff;padding:2px 8px;border-radius:4px;font-size:12px;">{esc(t['trigger'].replace('_', ' '))}</span>
          </td>
          <td style="padding:8px;border-bottom:1px solid #333;">{esc(t['platform'].title())}</td>
          <td style="padding:8px;border-bottom:1px solid #333;"><strong>${t['price']:.2f}</strong>{prev}</td>
          <td style="padding:8px;border-bottom:1px solid #333;">
            <a href="{esc(t.get('url', '#'))}" style="color:#63b3ed;">View Listing →</a>
          </td>
        </tr>"""

    html_body = f"""
    <html><body style="background:#1a1a2e;color:#e2e8f0;font-family:Arial,sans-serif;padding:24px;">
      <h2 style="color:#63b3ed;">🎟 TicketWatch Alert</h2>
      <p><strong>{esc(event['event'])}</strong><br>
         {esc(event.get('venue', ''))} &bull; {esc(event['date'])} &bull; {esc(event.get('city', ''))}</p>
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
        Your target: ${esc(event.get('max_price', '—'))} &bull; Qty needed: {esc(event.get('quantity', '—'))}<br>
        Next check scheduled automatically.
      </p>
    </body></html>"""

    ok = send_email(NOTIFY_EMAIL, subject, html_body)
    print(f"[EMAIL] Alert {'sent' if ok else 'FAILED'}: {subject}")
    return ok


# ── Weekly digest ─────────────────────────────────────────────────────────────

def _latest_low(conn, event_id, platform, before=None):
    """Most recent lowest_price for a platform, optionally before a timestamp."""
    if before:
        row = conn.execute(
            "SELECT lowest_price FROM price_history "
            "WHERE event_id=? AND platform=? AND checked_at < ? "
            "ORDER BY checked_at DESC LIMIT 1",
            (event_id, platform, before)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT lowest_price FROM price_history "
            "WHERE event_id=? AND platform=? "
            "ORDER BY checked_at DESC LIMIT 1",
            (event_id, platform)
        ).fetchone()
    return row[0] if row else None


def send_digest():
    conn = sqlite3.connect(DB_PATH)
    events = json.loads(EVENTS_PATH.read_text())
    today = datetime.date.today()
    week_ago = (datetime.datetime.now(timezone.utc)
                - datetime.timedelta(days=7)).isoformat()

    rows = ""
    for event in events:
        if not event.get("digest", True):
            continue

        try:
            event_date = datetime.date.fromisoformat(event["date"])
            delta = (event_date - today).days
            days_until = f"{delta}d" if delta >= 0 else "past"
        except (ValueError, TypeError, KeyError):
            days_until = "?"

        current = {}
        for platform in PRICE_PLATFORMS:
            price = _latest_low(conn, event["id"], platform)
            current[platform] = price

        # Trend: this week's cross-platform low vs the low from >= 7 days ago
        now_lows = [p for p in current.values() if p is not None]
        old_lows = [p for p in
                    (_latest_low(conn, event["id"], plat, before=week_ago)
                     for plat in PRICE_PLATFORMS)
                    if p is not None]
        if now_lows and old_lows:
            diff = min(now_lows) - min(old_lows)
            trend = "↓" if diff < 0 else ("↑" if diff > 0 else "→")
            trend_color = ("#48bb78" if diff < 0
                           else ("#fc8181" if diff > 0 else "#a0aec0"))
        else:
            trend = "—"
            trend_color = "#a0aec0"

        def fmt(p):
            return f"${p:.2f}" if p is not None else "—"

        rows += f"""
        <tr>
          <td style="padding:10px;border-bottom:1px solid #333;">{esc(event['event'])}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">{esc(event['date'])}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">{days_until}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">{fmt(current['stubhub'])}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">{fmt(current['seatgeek'])}</td>
          <td style="padding:10px;border-bottom:1px solid #333;">${esc(event.get('max_price', '—'))}</td>
          <td style="padding:10px;border-bottom:1px solid #333;color:{trend_color};font-size:18px;">{trend}</td>
        </tr>"""

    conn.close()

    subject = (f"[TicketWatch Weekly] {len(events)} events tracked — "
               f"{today.strftime('%b %d, %Y')}")
    html_body = f"""
    <html><body style="background:#1a1a2e;color:#e2e8f0;font-family:Arial,sans-serif;padding:24px;">
      <h2 style="color:#63b3ed;">🎟 TicketWatch Weekly Digest</h2>
      <p style="color:#a0aec0;">{today.strftime('%A, %B %d, %Y')}</p>
      <table style="width:100%;border-collapse:collapse;margin-top:16px;">
        <thead>
          <tr style="color:#a0aec0;font-size:11px;text-transform:uppercase;">
            <th style="padding:10px;text-align:left;">Event</th>
            <th style="padding:10px;text-align:left;">Date</th>
            <th style="padding:10px;text-align:left;">Days Out</th>
            <th style="padding:10px;text-align:left;">StubHub Low</th>
            <th style="padding:10px;text-align:left;">SeatGeek Low</th>
            <th style="padding:10px;text-align:left;">Your Target</th>
            <th style="padding:10px;text-align:left;">Trend (7d)</th>
          </tr>
        </thead>
        <tbody>{rows}</tbody>
      </table>
      <p style="margin-top:24px;color:#a0aec0;font-size:12px;">
        Sent by TicketWatch &bull; {datetime.datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
      </p>
    </body></html>"""

    ok = send_email(NOTIFY_EMAIL, subject, html_body)
    print(f"[EMAIL] Digest {'sent' if ok else 'FAILED'} to {NOTIFY_EMAIL}")
    if not ok:
        raise SystemExit(1)   # fail the workflow so you notice in Actions


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["digest"], required=True)
    args = parser.parse_args()
    if args.mode == "digest":
        send_digest()
