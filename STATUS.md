# TicketWatch — Project Status

_Last updated: 2026-07-11_

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

**Not set yet:**
- `STUBHUB_CLIENT_ID` / `STUBHUB_CLIENT_SECRET`. Applied via email to
  affiliates@stubhub.com; awaiting their approval (no self-serve signup
  exists for StubHub's API).
- `SCRAPERAPI_KEY` — sign up free at scraperapi.com (1,000 req/mo, no cost)
  and add as a repo secret to unblock SeatGeek in CI (see below). Code is
  already wired up; just needs the secret.

## Known, confirmed-permanent limitations
- **Ticketmaster pricing is permanently unavailable**: their support
  confirmed (2026-07-10) the Inventory Status/Partner API is restricted to
  official distribution partners, not obtainable on request. Not revisitable.

## Known limitations, workaround in place pending a secret
- **SeatGeek returns 403 from GitHub Actions specifically** (works fine from
  a residential IP with the same key/query). Confirmed 2026-07-11 it's an
  IP/ASN-level block, not a bot-signature check — a browser-like
  `User-Agent` made no difference. `fetcher.py`/`auto_suggest.py` now route
  SeatGeek calls through ScraperAPI's rotating-IP proxy when `SCRAPERAPI_KEY`
  is set (free tier, 1,000 req/mo — comfortably covers current volume).
  Until that secret is added, SeatGeek keeps failing in CI and StubHub is
  the working CI price source.
- Researched paid ticket-data aggregators (TicketsData: StubHub + SeatGeek +
  VividSeats + TickPick + Gametime in one API) as an alternative — starts at
  $499/mo, not worth it for a 10-event personal tracker. Vivid Seats and
  Ticket Evolution both have real APIs but need a business/broker
  application similar to StubHub's; skipped for now per user decision
  (2026-07-11) — StubHub + SeatGeek is enough sources.

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
2. Sign up for a free ScraperAPI account and add `SCRAPERAPI_KEY` as a repo
   secret to unblock SeatGeek in CI — code is ready, just needs the key.
3. Add more events to `data/events.json` as needed — no code changes required.
