"""
alert_engine.py
Compares current prices against targets and prior snapshots.
Fires email alerts when trigger conditions are met.
"""

import datetime
import sqlite3
from email_sender import send_alert_email


def get_last_price(conn, event_id, platform):
    """Return the previous price snapshot for dedup."""
    row = conn.execute(
        """
        SELECT lowest_price, checked_at FROM price_history
        WHERE event_id = ? AND platform = ?
        ORDER BY checked_at DESC
        LIMIT 1 OFFSET 1
        """,
        (event_id, platform)
    ).fetchone()
    return row[0] if row else None


def already_alerted(conn, event_id, platform, trigger_type, within_hours=24):
    """Return True if we already sent this alert within the dedup window."""
    cutoff = (datetime.datetime.utcnow() - datetime.timedelta(hours=within_hours)).isoformat()
    row = conn.execute(
        """
        SELECT id FROM alert_log
        WHERE event_id = ? AND platform = ? AND trigger_type = ? AND fired_at > ?
        """,
        (event_id, platform, trigger_type, cutoff)
    ).fetchone()
    return row is not None


def log_alert(conn, event_id, platform, trigger_type, price, now):
    conn.execute(
        "INSERT INTO alert_log (event_id, platform, trigger_type, price, fired_at) VALUES (?,?,?,?,?)",
        (event_id, platform, trigger_type, price, now)
    )
    conn.commit()


def evaluate_triggers(event, results, conn, now):
    triggers_fired = []

    for result in results:
        platform = result["platform"]
        price = result["lowest_price"]
        url = result.get("url", "")

        # Trigger 1: Price at or below target
        if price <= event.get("max_price", float("inf")):
            trigger = "PRICE_ALERT"
            if not already_alerted(conn, event["id"], platform, trigger):
                print(f"  [ALERT] {trigger} — {platform} @ ${price:.2f} (target: ${event['max_price']})")
                triggers_fired.append({"trigger": trigger, "platform": platform, "price": price, "url": url})
                log_alert(conn, event["id"], platform, trigger, price, now)

        # Trigger 2: New listing (price dropped since last check)
        last_price = get_last_price(conn, event["id"], platform)
        if last_price is None:
            pass  # First check, no comparison
        elif price < last_price:
            trigger = "NEW_LISTING"
            if not already_alerted(conn, event["id"], platform, trigger):
                print(f"  [ALERT] {trigger} — {platform} dropped ${last_price:.2f} → ${price:.2f}")
                triggers_fired.append({"trigger": trigger, "platform": platform, "price": price, "url": url, "prev_price": last_price})
                log_alert(conn, event["id"], platform, trigger, price, now)

    if triggers_fired:
        send_alert_email(event, triggers_fired)
