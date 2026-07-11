# TicketWatch — Project Status

_Last updated: 2026-07-11_

## What this is
A personal GitHub Actions agent that monitors ticket prices (StubHub, SeatGeek;
Ticketmaster for discovery only) against a watchlist in `data/events.json`,
and emails alerts. Repo: `MerckBot/TicketAgent`, local clone at
`/Users/jmerck/Downloads/ticketwatch`.

## Current version: v1.3
- Ticketmaster is **not** a price source (see below) — used only by
  `auto_suggest.py` to discover new shows for artists/teams in
  `data/preferences.json`.
- StubHub + SeatGeek are the price sources.
- **SeatGeek runs on a self-hosted runner, StubHub/Ticketmaster on GitHub-hosted
  runners** (see below) — split across four workflows instead of two.
- Per-(event, platform) elapsed-time scheduling (`platform_state` table,
  replaced the old per-event-only `event_state`), DB committed back to the
  repo each run.
- Email: SMTP (Gmail) is the working path. SendGrid is configured but unused
  since it needs a verified sender (`SENDGRID_FROM`) we haven't set up.
- Full history: see `CHANGELOG.md` and README's "Known limitations" section.

## GitHub secrets set
`TICKETMASTER_KEY`, `SEATGEEK_CLIENT_ID`, `SENDGRID_API_KEY`, `NOTIFY_EMAIL`,
`SMTP_USER`, `SMTP_PASS` — all working.

**Not set yet:** `STUBHUB_CLIENT_ID` / `STUBHUB_CLIENT_SECRET`. Applied via
email to affiliates@stubhub.com; awaiting their approval (no self-serve
signup exists for StubHub's API).

**No longer used:** `SCRAPERAPI_KEY` — was added 2026-07-11 to try tunneling
SeatGeek through ScraperAPI's proxy, but even ScraperAPI's own default pool
got 403/500'd by SeatGeek's block, and their residential/premium pool (the
tier that might work) costs 10x credits/request — would blow the whole
monthly free allowance in days at this project's volume. Abandoned in favor
of a self-hosted runner. If you still have this secret set in GitHub, it's
harmless but unused — fine to delete via `gh secret remove SCRAPERAPI_KEY -R
MerckBot/TicketAgent`.

## Known, confirmed-permanent limitations
- **Ticketmaster pricing is permanently unavailable**: their support
  confirmed (2026-07-10) the Inventory Status/Partner API is restricted to
  official distribution partners, not obtainable on request. Not revisitable.
- **SeatGeek 403s every GitHub-hosted-runner request** (confirmed 2026-07-06,
  reconfirmed via ScraperAPI proxy 2026-07-11) — genuine IP/ASN-level block,
  not fixable with a header change or any proxy tier viable on a free budget.
  **Resolved architecturally**: SeatGeek now runs on a self-hosted runner
  (real residential IP, not blocked) instead of fighting the block in the
  cloud. See "Self-hosted runner" below — this is the one manual step left.
- Researched paid ticket-data aggregators (TicketsData: StubHub + SeatGeek +
  VividSeats + TickPick + Gametime in one API) as an alternative — starts at
  $499/mo, not worth it for a 10-event personal tracker. Vivid Seats and
  Ticket Evolution both have real APIs but need a business/broker
  application similar to StubHub's; skipped per user decision (2026-07-11).

## Self-hosted runner — the one thing left to do
Register a self-hosted GitHub Actions runner on a machine you control (this
Mac, presumably) so `check_prices_selfhosted.yml` and
`scan_new_events_selfhosted.yml` have something to run on:
1. Repo → Settings → Actions → Runners → New self-hosted runner → follow
   GitHub's shown download/config commands.
2. Install as a persistent service so it survives reboots/logouts (`./svc.sh
   install && ./svc.sh start` on macOS/Linux).
3. That's it — the two `*_selfhosted.yml` workflows already target
   `runs-on: self-hosted` and will start picking up queued runs once the
   runner is online. If it's ever offline when the schedule fires, the run
   just queues; the per-(event, platform) due-check means a delayed run is a
   no-op catch-up, never a lost check.

The user asked me to hold off doing this myself (2026-07-11) — it installs a
persistent background service on their machine, which they wanted to do by
hand rather than have me execute. Code side (workflows, `--platforms` CLI
flag, DB schema) is fully done and tested; only the runner registration
itself is outstanding.

## Tracked events
10 events in `data/events.json` (Wizard of Oz x3, Bills x2, Sabres/Capitals
[date TBD pending NHL schedule], Zach Bryan x2, Pitbull, Harry Styles).

## Local machine notes
- `gh` CLI installed via Homebrew at `/opt/homebrew/bin/gh` (not `brew`
  itself on PATH — use full path or `brew shellenv`).
- `gh auth` has `workflow` scope (needed to push changes under
  `.github/workflows/`); run `gh auth setup-git` if pushes get rejected
  with a credential-helper mismatch (macOS Keychain can cache a stale token).
- Repo-local git identity is set (not global): `MerckBot
  <296020564+MerckBot@users.noreply.github.com>`.
- Actions → workflow permissions is set to **read/write** (required for the
  DB-commit-back approach).
- This Mac is Apple Silicon (arm64) — pick the matching runner package if
  setting up the self-hosted runner here.
- As of 2026-07-11, `data/prices.db` has **zero rows** in `price_history` and
  `seen_events` despite every CI run "succeeding" — StubHub has been
  credential-less and SeatGeek always 403'd, so no real price/discovery data
  has been captured yet. Not a bug; it'll start populating once StubHub is
  approved and/or the self-hosted runner is online.

## Open next steps
1. Register the self-hosted runner (see above) to activate SeatGeek checking
   and discovery scanning.
2. Wait for StubHub approval; when it arrives, set
   `STUBHUB_CLIENT_ID`/`STUBHUB_CLIENT_SECRET` as secrets.
3. Optionally delete the now-unused `SCRAPERAPI_KEY` secret.
4. Add more events to `data/events.json` as needed — no code changes required.
