# Changelog

## v1.2 — 2026-07-02

### Breaking / scope
- **Ticketmaster removed as a price source** (Discovery API has no live prices; Inventory Status API pending approval). TM still powers new-event scanning and buy links. Digest drops the TM Low column.

### Critical fixes
- **DB persistence**: replaced Actions cache (immutable keys froze the DB permanently; scan + digest were reading a day-one snapshot forever, causing duplicate "new show" emails daily) with committing `prices.db` to the repo. Added `concurrency` group + `contents: write` to serialize all DB writers. Removed the broken duplicate cache-save step.
- **Alert delivery**: alerts now log to `alert_log` only after the email sends successfully. Previously a failed send was recorded as sent and suppressed by the 24h dedup — silently missed alerts.
- **SendGrid**: sender now comes from the `SENDGRID_FROM` secret (verified sender). Hardcoded `ticketwatch@noreply.com` guaranteed 403s. Send errors are caught and fall back to SMTP instead of crashing the run.
- **check_prices.yml** now passes `SMTP_USER`/`SMTP_PASS` (the alert path previously had no working SMTP fallback).

### Logic fixes
- **Scheduling**: per-event `last_checked` (new `event_state` table) with elapsed-time intervals, replacing exact hour-match logic that GitHub's delayed/skipped cron runs could miss for a full day or week.
- **Digest trend**: now compares this week's cross-platform low vs the low ≥7 days ago. Previously compared the last two rows regardless of platform (usually two different platforms from the same run).
- **City matching**: `"City, ST"` split into city + state params for Ticketmaster (`city`/`stateCode`) and SeatGeek (`venue.city`/`venue.state`). Previously the combined string likely matched nothing.
- **PRICE_DROP** (renamed from NEW_LISTING): fires only on drops ≥5%, not any $0.01 tick.
- **Missing `max_price`** no longer fires an alert on every price and then crashes; the target trigger is skipped with a warning.
- **Day-of coverage**: checks continue through `days_until == -1` so US evening events aren't dropped when UTC rolls over.
- **Auto-suggest seeding**: first run (empty `seen_events`) stores a baseline without emailing, instead of blasting up to ~100 "new" events. `--seed` flag forces this.
- **Duplicate event ids** in events.json now fail fast instead of corrupting history.

### Robustness
- Every fetcher/scanner skips cleanly with a log line when its credentials aren't configured — safe to run with only the TM key today.
- SeatGeek scan has a date floor (no past events); `datetime_local: null` no longer crashes.
- `$0` prices handled (`is not None` instead of truthiness); non-numeric prices skipped.
- API-sourced strings HTML-escaped in all emails.
- `datetime.utcnow()` → timezone-aware `datetime.now(timezone.utc)`.
- Token cache moved from useless `/tmp` file to in-memory per run.
- Added DB index on `(event_id, platform, checked_at)`.
- "TBD" dates log an explicit warning instead of silently never checking.
- Failed digest sends exit non-zero so the Actions run shows red.

## v1.1
- Initial multi-platform build (Ticketmaster, StubHub, SeatGeek) with Actions-cache persistence.
