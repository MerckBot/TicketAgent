# TicketWatch — Project Status

_Last updated: 2026-07-10_

## What this is
A personal GitHub Actions agent that monitors ticket prices (StubHub, SeatGeek;
Ticketmaster for discovery only) against a watchlist in `data/events.json`,
and emails alerts. Repo: `MerckBot/TicketAgent`, local clone at
`/Users/jmerck/Downloads/ticketwatch`.

## Current version: v1.2
- Ticketmaster is **not** a price source (see below) — used only by
  `auto_suggest.py` to discover new shows for artists/teams in
  `data/preferences.json`.
- StubHub + SeatGeek are the price sources.
- Per-event elapsed-time scheduling (`event_state` table), DB committed back
  to the repo each run (replaced broken Actions-cache persistence).
- Email: SMTP (Gmail) is the working path. SendGrid is configured but unused
  since it needs a verified sender (`SENDGRID_FROM`) we haven't set up.
- Full history: see `CHANGELOG.md` and README's "Known limitations" section.

## GitHub secrets set
`TICKETMASTER_KEY`, `SEATGEEK_CLIENT_ID`, `SENDGRID_API_KEY`, `NOTIFY_EMAIL`,
`SMTP_USER`, `SMTP_PASS` — all working.

**Not set yet:** `STUBHUB_CLIENT_ID` / `STUBHUB_CLIENT_SECRET`. Applied via
email to affiliates@stubhub.com; awaiting their approval (no self-serve
signup exists for StubHub's API).

## Known, confirmed-permanent limitations
- **Ticketmaster pricing is permanently unavailable**: their support
  confirmed (2026-07-10) the Inventory Status/Partner API is restricted to
  official distribution partners, not obtainable on request. Not revisitable.
- **SeatGeek returns 403 from GitHub Actions specifically** (works fine from
  a residential IP with the same key/query) — looks like GitHub Actions'
  runner IPs are blocked by SeatGeek or a WAF in front of it. Unresolved;
  StubHub is meant to be the working CI price source once approved.

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

## Open next steps
1. Wait for StubHub approval; when it arrives, set
   `STUBHUB_CLIENT_ID`/`STUBHUB_CLIENT_SECRET` as secrets.
2. Decide whether to pursue the SeatGeek-from-Actions 403 further (contact
   support / proxy) or just leave StubHub as the CI price source.
3. Add more events to `data/events.json` as needed — no code changes required.
