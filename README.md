# TicketWatch Agent v1.1

Monitors Ticketmaster, StubHub, and SeatGeek. Alerts you by email when prices drop or new tickets post.

---

## Setup

### 1. Clone and configure

```bash
git clone <your-repo>
cd ticketwatch
```

Edit `data/events.json` to add events you want to track.  
Edit `data/preferences.json` to update your artist/team/venue list.  
`data/notify.json` has your email and digest schedule.

### 2. Add GitHub Secrets

Go to **Settings → Secrets and variables → Actions** in your repo and add:

| Secret | Where to get it |
|--------|----------------|
| `TICKETMASTER_KEY` | developer.ticketmaster.com |
| `STUBHUB_CLIENT_ID` | developer.stubhub.com (see Section 9 of build spec) |
| `STUBHUB_CLIENT_SECRET` | developer.stubhub.com |
| `SEATGEEK_CLIENT_ID` | seatgeek.com/account/develop |
| `SENDGRID_API_KEY` | sendgrid.com (free tier: 100 emails/day) |
| `NOTIFY_EMAIL` | jmerck2d2@gmail.com |
| `SMTP_USER` | (optional Gmail address if not using SendGrid) |
| `SMTP_PASS` | (optional Gmail app password) |

### 3. StubHub OAuth (one-time)

1. Go to [developer.stubhub.com](https://developer.stubhub.com), create an app
2. Set redirect URI to `http://localhost:8080/callback`
3. Save Client ID and Client Secret as GitHub secrets (above)

The agent uses Client Credentials flow — no user login needed.

### 4. Run locally

```bash
pip install -r requirements.txt
cd agent
python fetcher.py        # Price check
python auto_suggest.py   # Scan for new events
python email_sender.py --mode digest  # Send weekly digest
```

---

## How it works

- **check_prices.yml** — runs hourly; Python skips events not due yet based on proximity window
- **weekly_digest.yml** — every Monday 8am UTC
- **scan_new_events.yml** — daily 9am UTC; alerts on new shows for your tracked artists/teams

### Check frequency

| Days until event | Frequency |
|-----------------|-----------|
| > 30 days | Weekly |
| ≤ 30 days | Daily |
| ≤ 7 days | Every 6 hours |
| Day of | Every 2 hours |

---

## File structure

```
ticketwatch/
  .github/workflows/
    check_prices.yml
    weekly_digest.yml
    scan_new_events.yml
  agent/
    fetcher.py          # Platform API calls + DB writes
    alert_engine.py     # Trigger evaluation
    email_sender.py     # Alert + digest emails
    auto_suggest.py     # New event scanner
    token_manager.py    # StubHub OAuth token refresh
  data/
    events.json         # Your watchlist
    preferences.json    # Artists / teams / venues
    notify.json         # Email config
    prices.db           # SQLite (auto-created on first run)
  requirements.txt
  README.md
```

---

## Adding events

Edit `data/events.json`:

```json
[
  {
    "id": "event_002",
    "event": "Bruce Springsteen",
    "date": "2026-09-15",
    "venue": "Capital One Arena",
    "city": "Washington, DC",
    "max_price": 200,
    "quantity": 2,
    "section_pref": "any",
    "row_pref": "any",
    "digest": true
  }
]
```

Each event needs a unique `id`. No code change required.
