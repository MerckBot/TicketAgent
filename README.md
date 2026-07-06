# TicketWatch Agent v1.2

Monitors StubHub and SeatGeek prices. Alerts you by email when prices hit your target or drop ≥5%. Scans Ticketmaster + SeatGeek daily for new shows matching your artists/teams.

**v1.2 change in scope:** Ticketmaster is no longer a price source. Its public Discovery API returns static face-value ranges (often missing), not live prices — real prices require the Inventory Status API, which needs approval (devportalinquiry@ticketmaster.com). TM is still used for new-event discovery and buy links. If/when Inventory Status access is granted, it can be added back as a price source.

---

## Setup

### 1. Clone and configure

```bash
git clone <your-repo>
cd ticketwatch
```

Edit `data/events.json` to add events you want to track.
Edit `data/preferences.json` to update your artist/team/venue list.
`data/notify.json` has your email config.

### 2. Add GitHub Secrets

Go to **Settings → Secrets and variables → Actions** and add:

| Secret | Where to get it | Required |
|--------|----------------|----------|
| `TICKETMASTER_KEY` | developer.ticketmaster.com | For new-event scanning |
| `STUBHUB_CLIENT_ID` / `STUBHUB_CLIENT_SECRET` | developer.stubhub.com | For StubHub prices |
| `SEATGEEK_CLIENT_ID` | seatgeek.com/account/develop | For SeatGeek prices + scanning |
| `SENDGRID_API_KEY` | sendgrid.com | For email (or use SMTP) |
| `SENDGRID_FROM` | Your **verified sender** address in SendGrid | With SendGrid |
| `NOTIFY_EMAIL` | Where alerts go | Yes |
| `SMTP_USER` / `SMTP_PASS` | Gmail address + app password | SMTP fallback |

Missing credentials are fine — each platform is skipped with a log line until its secret exists. Add them as API approvals come in; no code changes needed.

### 3. Enable workflow write access

The workflows commit `data/prices.db` back to the repo (this replaced the broken Actions-cache persistence). In **Settings → Actions → General → Workflow permissions**, select **Read and write permissions**.

### 4. Run locally

```bash
pip install -r requirements.txt
cd agent
python fetcher.py                      # Price check
python auto_suggest.py                 # Scan for new events
python auto_suggest.py --seed          # Baseline current events, no email
python email_sender.py --mode digest   # Send weekly digest
```

---

## How it works

- **check_prices.yml** — hourly; each event is checked when enough time has elapsed since its own `last_checked` (stored in the DB), so a delayed or skipped GitHub cron run just gets picked up next hour instead of losing a day or week
- **scan_new_events.yml** — daily 9am UTC; first run seeds a baseline silently, then alerts only on genuinely new shows
- **weekly_digest.yml** — Mondays 8am UTC; per-event lows plus a 7-day trend arrow

### Check frequency

| Days until event | Interval |
|-----------------|----------|
| > 30 days | Weekly |
| 8–30 days | Daily |
| 2–7 days | Every 6 hours |
| Day before + day of | Every 2 hours |

Checks continue one day past the event date to cover the UTC/local timezone gap on game day.

### Alert rules

- **PRICE ALERT** — a platform low is at or below your `max_price`
- **PRICE DROP** — a platform low dropped ≥5% since the previous check
- Each alert type dedupes per event/platform for 24h
- Alerts are only recorded after the email actually sends — a failed send retries on the next check

---

## Persistence

`data/prices.db` (SQLite) is committed back to the repo by the workflows after each run, with a `concurrency` group serializing all writers. Price history is durable and visible in git history. (v1.1 used Actions cache, which is immutable per key and evicted after 7 days — it silently froze and lost data.)

---

## Known limitations

- `quantity`, `section_pref`, and `row_pref` in events.json are informational only — the fetched "lowest price" may be a single seat in any section. Enforcing them needs listing-level API access.
- Events with `date: "TBD"` are skipped (with a log warning) until a real date is set.
- The StubHub endpoint/auth in `token_manager.py` is from their older developer program — verify against whatever their API team sends with your credentials.

---

## Adding events

Edit `data/events.json`. Each event needs a unique `id`, a real `date` (YYYY-MM-DD), and a `max_price`. No code change required.
