"""
alert_engine.py (v1.2)
Compares current prices against targets and prior snapshots.
Fires email alerts when trigger conditions are met.

v1.2 changes:
- Alerts are logged AFTER the email sends successfully. A failed send is no
  longer silently swallowed by the 24h dedup window.
- "NEW_LISTING" renamed to "PRICE_DROP" and now requires a >= 5% drop.
- Missing max_price no longer fires on every price (or crashes) — the
  target trigger is skipped with a warning instead.
"""

import datetime
from datetime import timezone

from email_sender import send_alert_email

DROP_THRESHOLD_PCT = 5.0   # minimum % drop before PRICE_DROP fires


def get_last_price(conn, event_id, platform):
    """Previous snapshot (the row before the one inserted this run)."""
    row = conn.execute(
        """
        SELECT lowest_price FROM price_history
        WHERE event_id = ? AND platform = ?
        ORDER BY checked_at DESC, id DESC
        LIMIT 1 OFFSET 1
        """,
        (event_id, platform)
    ).fetchone()
    return row[0] if row else None


def already_alerted(conn, event_id, platform, trigger_type, within_hours=24):
    cutoff = (datetime.datetime.now(timezone.utc)
              - datetime.timedelta(hours=within_hours)).isoformat()
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
        "INSERT INTO alert_log (event_id, platform, trigger_type, price, fired_at) "
        "VALUES (?,?,?,?,?)",
        (event_id, platform, trigger_type, price, now)
    )
    conn.commit()


def evaluate_triggers(event, results, conn, now):
    triggers_fired = []
    max_price = event.get("max_price")

    for result in results:
        platform = result["platform"]
        price = result["lowest_price"]
        url = result.get("url", "")

        # Trigger 1: price at or below target
        if max_price is None:
            print(f"  [WARN] {event.get('id','?')} has no max_price — "
                  f"target alert skipped")
        elif price <= max_price:
            trigger = "PRICE_ALERT"
            if not already_alerted(conn, event["id"], platform, trigger):
                print(f"  [ALERT] {trigger} — {platform} @ ${price:.2f} "
                      f"(target: ${max_price})")
                triggers_fired.append({"trigger": trigger, "platform": platform,
                                       "price": price, "url": url})

        # Trigger 2: meaningful price drop since last check (>= 5%)
        last_price = get_last_price(conn, event["id"], platform)
        if last_price:
            drop_pct = (last_price - price) / last_price * 100.0
            if drop_pct >= DROP_THRESHOLD_PCT:
                trigger = "PRICE_DROP"
                if not already_alerted(conn, event["id"], platform, trigger):
                    print(f"  [ALERT] {trigger} — {platform} dropped "
                          f"${last_price:.2f} → ${price:.2f} ({drop_pct:.1f}%)")
                    triggers_fired.append({"trigger": trigger, "platform": platform,
                                           "price": price, "url": url,
                                           "prev_price": last_price})

    if not triggers_fired:
        return

    # Send first; only log (which arms the 24h dedup) if the send succeeded.
    if send_alert_email(event, triggers_fired):
        for t in triggers_fired:
            log_alert(conn, event["id"], t["platform"], t["trigger"],
                      t["price"], now)
    else:
        print(f"  [WARN] Alert email failed for {event.get('id','?')} — "
              f"not logged, will retry next check")
