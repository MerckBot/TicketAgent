# Changelog

## v1.3 — 2026-07-11

### SeatGeek CI 403 — investigated and resolved via self-hosted runner
- Confirmed the 403 SeatGeek returns to GitHub-hosted runners (first seen 2026-07-06) is IP/ASN-level, not a bot-signature check: a browser-like `User-Agent` made no difference, and it isn't fixable with a rotating-IP proxy either — ScraperAPI's default free-tier pool got the same block, and its residential/premium pool (the tier that might work) costs 10x credits/request, which would exhaust the whole monthly free allowance in days at this project's call volume.
- Researched alternative price sources instead of fighting the block further: Vivid Seats and Ticket Evolution both have real APIs but need a business/broker application (same wait as StubHub); TickPick has no direct public API; aggregators like TicketsData bundle everything into one API but start at $499/mo — none of this is worth it for a 10-event personal tracker.
- Resolved by splitting SeatGeek onto a self-hosted runner (a real residential IP isn't blocked at all), while StubHub and Ticketmaster keep running on GitHub-hosted runners unaffected.
- **Scheduling refactor required for this split**: `event_state` (one `last_checked` per event) replaced with `platform_state` (one `last_checked` per event **and** platform). Previously, checking any platform marked the whole event "checked," so two workflows checking different platforms on independent schedules would have starved each other. `fetcher.py` and `auto_suggest.py` both take an optional `--platforms` CLI flag to restrict which fetchers/scanners run in a given invocation.
- New workflows `check_prices_selfhosted.yml` / `scan_new_events_selfhosted.yml` (SeatGeek only, `runs-on: self-hosted`); the existing `check_prices.yml` / `scan_new_events.yml` now run StubHub-only / Ticketmaster-only respectively.

## v1.2 — 2026-07-02

### Breaking / scope
- **Ticketmaster removed as a price source** (Discovery API has no live prices; the Inventory Status/Partner API that does is a closed API restricted to Ticketmaster's official distribution partners — confirmed via their support team 2026-07-10, not obtainable by request). TM still powers new-event scanning and buy links. Digest drops the TM Low column.

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
