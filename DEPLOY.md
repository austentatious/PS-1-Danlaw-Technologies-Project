# RAR EMS — Company Server Deployment Guide

## Files overview

| File | Purpose |
|---|---|
| `app.py` | Python backend server (replaces Cloudflare Worker) |
| `frontend/index.html` | The web app — serve this as a static file |
| `schema.sql` | Reference only — SQLite DB is created automatically |
| `wrangler.toml` | Cloudflare only — not needed on company server |

---

## Step 1 — Install Python dependencies (once)

```bash
pip install flask apscheduler requests
```

---

## Step 2 — Configure app.py

Open `app.py` and set these at the top:

```python
PORT = 5000   # Change if needed

# If using Resend for email:
RESEND_API_KEY  = "re_your_key_here"
EMAIL_FROM      = "noreply@danlaw.com"   # Must be your verified domain
EMAIL_FROM_NAME = "RAR EMS"

# If using company SMTP instead (set USE_SMTP = True):
USE_SMTP      = True
SMTP_HOST     = "smtp.danlaw.com"
SMTP_PORT     = 587
SMTP_USER     = "noreply@danlaw.com"
SMTP_PASSWORD = "your_smtp_password"
```

---

## Step 3 — Configure index.html

Open `frontend/index.html` and update line 13:

```javascript
window.RAR_API_BASE = "http://COMPANY-SERVER-IP:5000";
// Example: window.RAR_API_BASE = "http://192.168.1.50:5000";
```

---

## Step 4 — Run the server

```bash
python app.py
```

The server starts on port 5000. The SQLite database (`rar_ems.db`) is
created automatically in the same folder. The 10-minute email digest
scheduler starts automatically — no cron job setup needed.

---

## Step 5 — Serve index.html

Option A — Open directly in browser (simplest):
- Just open `frontend/index.html` in a browser on the company network

Option B — Serve via Nginx or Apache (for multi-user access):
- Point the web server's root to the `frontend/` folder

---

## Step 6 — Keep server running (optional)

To keep the server running after logout, use one of:

```bash
# Option A — nohup (simple)
nohup python app.py &

# Option B — screen
screen -S rar-ems
python app.py
# Ctrl+A then D to detach

# Option C — systemd service (recommended for permanent deployment)
# Ask IT to set up a systemd service for app.py
```

---

## Email setup

### Option A: Resend (if no company SMTP available)
1. Sign up at resend.com
2. Add and verify `danlaw.com` domain (IT team adds 2 DNS records)
3. Use any `@danlaw.com` address as From Email
4. All recipients work with no restrictions

### Option B: Company SMTP (recommended)
- No external service needed
- Set `USE_SMTP = True` in `app.py`
- Ask IT for SMTP host, port, username, password
- All recipient emails work immediately

---

## Data migration from Cloudflare

All existing RAR data is stored in Cloudflare's D1 database. To migrate:
1. Open the app on Cloudflare while it still works
2. Use the Export to Excel feature to download all data
3. On the company server, import the data via the app's interface

---

## Differences from Cloudflare version

| Feature | Cloudflare | Company Server |
|---|---|---|
| Backend | Python Worker | Flask (app.py) |
| Database | Cloudflare D1 | SQLite (local file) |
| Scheduler | Cloudflare Cron | APScheduler (built-in) |
| Email | Resend only | Resend OR company SMTP |
| Hosting cost | Free | Company server (already owned) |
