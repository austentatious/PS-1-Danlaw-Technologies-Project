"""
RAR EMS — Company Server Backend
Drop-in replacement for worker/entry.py (Cloudflare) using Flask + SQLite.

Requirements (install once on the server):
    pip install flask apscheduler requests

Run:
    python app.py

The server starts on port 5000 by default.
Change PORT below if needed.

Access the app from any LAN computer at:
    http://<server-ip>:5000

No changes needed in index.html — frontend and API are on the same server.

Email:
    Option A — Keep using Resend (recommended, same as Cloudflare setup):
        Set RESEND_API_KEY and EMAIL_FROM below.
    Option B — Use company SMTP server (no Resend account needed):
        Set SMTP_* variables below and set USE_SMTP = True.
"""

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone, timedelta

import requests
from flask import Flask, request, jsonify, Response, send_from_directory
from apscheduler.schedulers.background import BackgroundScheduler

# ── Configuration ─────────────────────────────────────────────────────────────

PORT        = 5000
DB_PATH     = "rar_ems.db"   # SQLite file — created automatically on first run

# Email — Option A: Resend (same as Cloudflare setup)
USE_SMTP        = False                         # Set True to use company SMTP instead
RESEND_API_KEY  = os.environ.get("RESEND_API_KEY", "re_PASTE_YOUR_KEY_HERE")
EMAIL_FROM      = os.environ.get("EMAIL_FROM",  "onboarding@resend.dev")
EMAIL_FROM_NAME = os.environ.get("EMAIL_FROM_NAME", "RAR EMS")

# Email — Option B: Company SMTP (set USE_SMTP = True above to use this)
SMTP_HOST     = os.environ.get("SMTP_HOST",     "smtp.danlaw.com")
SMTP_PORT     = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER     = os.environ.get("SMTP_USER",     "noreply@danlaw.com")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
SMTP_FROM     = os.environ.get("SMTP_FROM",     "noreply@danlaw.com")

# ── Flask app ─────────────────────────────────────────────────────────────────

app = Flask(__name__, static_folder='frontend', static_url_path='')
_db_lock = threading.Lock()


# ── SQLite helpers ────────────────────────────────────────────────────────────

def _get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE IF NOT EXISTS app_state "
        "(key TEXT PRIMARY KEY, value TEXT NOT NULL)"
    )
    conn.commit()
    return conn


def db_get(key):
    with _db_lock:
        conn = _get_conn()
        row  = conn.execute(
            "SELECT value FROM app_state WHERE key = ?", (key,)
        ).fetchone()
        conn.close()
    if not row:
        return None
    try:
        return json.loads(row["value"])
    except Exception:
        return None


def db_set(key, value):
    with _db_lock:
        conn = _get_conn()
        conn.execute(
            "INSERT INTO app_state (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value))
        )
        conn.commit()
        conn.close()


# ── Email sending ─────────────────────────────────────────────────────────────

def relay_email(subject, html_body, to_addresses, from_email=None, from_name=None):
    """Send email via Resend API or company SMTP depending on USE_SMTP setting."""
    if not to_addresses:
        return True

    _from_email = from_email or EMAIL_FROM
    _from_name  = from_name  or EMAIL_FROM_NAME

    if USE_SMTP:
        return _send_smtp(subject, html_body, to_addresses, _from_email, _from_name)
    else:
        return _send_resend(subject, html_body, to_addresses, _from_email, _from_name)


def _send_resend(subject, html_body, to_addresses, from_email, from_name):
    """Send via Resend API."""
    api_key = RESEND_API_KEY
    if not api_key or api_key == "re_PASTE_YOUR_KEY_HERE":
        print("[relay_email] RESEND_API_KEY not configured")
        return False
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Content-Type":  "application/json",
                "Authorization": f"Bearer {api_key}",
            },
            json={
                "from":    f"{from_name} <{from_email}>",
                "to":      list(to_addresses),
                "subject": subject,
                "html":    html_body,
            },
            timeout=15,
        )
        if resp.status_code not in (200, 201):
            print(f"[relay_email] Resend rejected: HTTP {resp.status_code} | {resp.text[:300]}")
            return False
        print(f"[relay_email] Email sent OK via Resend to {to_addresses}")
        return True
    except Exception as exc:
        print(f"[relay_email] Resend exception: {exc}")
        return False


def _send_smtp(subject, html_body, to_addresses, from_email, from_name):
    """Send via company SMTP server."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text      import MIMEText
    try:
        msg             = MIMEMultipart("alternative")
        msg["Subject"]  = subject
        msg["From"]     = f"{from_name} <{from_email}>"
        msg["To"]       = ", ".join(to_addresses)
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.ehlo()
            server.starttls()
            if SMTP_USER and SMTP_PASSWORD:
                server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, list(to_addresses), msg.as_string())
        print(f"[relay_email] Email sent OK via SMTP to {to_addresses}")
        return True
    except Exception as exc:
        print(f"[relay_email] SMTP exception: {exc}")
        return False


# ── Periodic digest (replaces Cloudflare Cron) ───────────────────────────────

def run_digest():
    """Called every 10 minutes by APScheduler — same logic as on_scheduled."""
    cfg = db_get("email_config_v1")
    if not cfg or not cfg.get("started"):
        return

    next_send_at = cfg.get("next_send_at")
    interval_hrs = int(cfg.get("interval_hours") or 24)
    recipients   = cfg.get("recipients") or []
    from_email   = cfg.get("from_email") or EMAIL_FROM
    from_name    = cfg.get("from_name")  or EMAIL_FROM_NAME

    if not next_send_at or not recipients:
        return

    now_ts = datetime.now(timezone.utc).timestamp()
    try:
        next_ts = datetime.fromisoformat(
            next_send_at.replace("Z", "+00:00")
        ).timestamp()
    except Exception:
        return

    if now_ts < next_ts:
        return

    state     = db_get("shared_state_v1")
    records   = (state or {}).get("records") or []
    open_recs = [
        r for r in records
        if isinstance(r, dict)
        and r.get("rarNo")
        and (r.get("status") or "").strip().lower() in ("open", "in progress", "inprogress")
    ]

    if open_recs:
        subject, html = _build_digest(open_recs, from_name)
        relay_email(subject, html, recipients, from_email, from_name)

    next_dt = datetime.fromisoformat(next_send_at.replace("Z", "+00:00"))
    while next_dt.timestamp() <= now_ts:
        next_dt += timedelta(hours=interval_hrs)

    cfg["next_send_at"] = next_dt.isoformat()
    cfg["last_sent_at"] = datetime.now(timezone.utc).isoformat()
    db_set("email_config_v1", cfg)


# ── CORS helper ───────────────────────────────────────────────────────────────

def _cors(response):
    response.headers["Access-Control-Allow-Origin"]  = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, PUT, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, x-app-key"
    return response


@app.after_request
def after_request(response):
    return _cors(response)




# ── Serve frontend ────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("frontend", "index.html")

@app.route("/<path:path>")
def static_files(path):
    # Serve any file from frontend/ (libs/chart.umd.js, libs/xlsx.full.min.js etc.)
    return send_from_directory("frontend", path)

# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/healthz")
def healthz():
    try:
        _get_conn().execute("SELECT 1").fetchone()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/api/state", methods=["GET", "PUT"])
def api_state():
    if request.method == "GET":
        state = db_get("shared_state_v1")
        if not state:
            return jsonify({"version": 0, "records": None, "users": None,
                            "refs": None, "prodmap": None})
        return jsonify(state)

    # PUT
    payload = request.get_json(force=True)

    # Detect brand-new RARs and fire instant alert
    prev        = db_get("shared_state_v1")
    prev_rarNos = {r["rarNo"] for r in (prev or {}).get("records") or []
                   if isinstance(r, dict) and r.get("rarNo")}
    new_records = payload.get("records") or []
    brand_new   = [
        rec for rec in new_records
        if isinstance(rec, dict)
        and rec.get("rarNo")
        and rec["rarNo"] not in prev_rarNos
        and (rec.get("status") or "open").strip().lower()
            in ("open", "in progress", "inprogress")
    ]

    if brand_new:
        cfg = db_get("email_config_v1")
        if cfg and cfg.get("started") and cfg.get("recipients"):
            target     = brand_new[-1]
            from_email = cfg.get("from_email") or EMAIL_FROM
            from_name  = cfg.get("from_name")  or EMAIL_FROM_NAME
            subj, html = _build_new_rar_email(target, from_name)
            relay_email(subj, html, cfg["recipients"], from_email, from_name)

    next_ver = int(payload.get("version") or 0) + 1
    state = {
        "records":    payload.get("records"),
        "users":      payload.get("users"),
        "refs":       payload.get("refs"),
        "prodmap":    payload.get("prodmap"),
        "rft_ppm":    payload.get("rft_ppm"),
        "version":    next_ver,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    db_set("shared_state_v1", state)
    return jsonify({"ok": True, "version": next_ver})


@app.route("/api/email-config", methods=["GET", "PUT"])
def api_email_config():
    if request.method == "GET":
        cfg = db_get("email_config_v1")
        return jsonify(cfg or {
            "started": False, "recipients": [],
            "next_send_at": None, "interval_hours": 24,
            "last_sent_at": None,
            "from_email": EMAIL_FROM, "from_name": EMAIL_FROM_NAME
        })
    cfg = request.get_json(force=True)
    db_set("email_config_v1", cfg)
    return jsonify({"ok": True})


@app.route("/api/send-email", methods=["POST"])
def api_send_email():
    body = request.get_json(force=True)
    cfg  = db_get("email_config_v1")
    if not cfg or not cfg.get("started"):
        return jsonify({"ok": False, "reason": "paused"})
    recipients = cfg.get("recipients") or []
    if not recipients:
        return jsonify({"ok": False, "reason": "no recipients"})
    from_email = cfg.get("from_email") or EMAIL_FROM
    from_name  = cfg.get("from_name")  or EMAIL_FROM_NAME
    ok = relay_email(
        body.get("subject", "RAR EMS Notification"),
        body.get("html", ""),
        recipients, from_email, from_name
    )
    return jsonify({"ok": ok})


# ── Email HTML builders (identical to Cloudflare version) ────────────────────

def _build_digest(open_recs, from_name):
    count = len(open_recs)
    rows  = "".join(
        f"<tr style=\"background:{'#f6f8fb' if i%2==0 else '#ffffff'};\">"
        f"<td style='padding:8px 10px;border:1px solid #dde3eb;font-weight:700;color:#2563a8;white-space:nowrap;width:80px;'>{r.get('rarNo','—')}</td>"
        f"<td style='padding:8px 10px;border:1px solid #dde3eb;white-space:nowrap;width:85px;'>{r.get('date','—')}</td>"
        f"<td style='padding:8px 10px;border:1px solid #dde3eb;width:100px;'>{r.get('customer','—')}</td>"
        f"<td style='padding:8px 10px;border:1px solid #dde3eb;width:130px;'>{r.get('product','—')}</td>"
        f"<td style='padding:8px 10px;border:1px solid #dde3eb;width:130px;'>{r.get('defectMode') or '—'}</td>"
        f"<td style='padding:8px 10px;border:1px solid #dde3eb;white-space:nowrap;width:65px;text-align:center;'>{r.get('category') or '—'}</td>"
        f"</tr>"
        for i, r in enumerate(open_recs)
    )
    subject = f"[Internal Rejection Management System] Periodic Reminder — {count} Open RAR(s) Require Attention"
    html = f"""<html><body style="font-family:Arial,sans-serif;color:#1c2b3f;max-width:720px;margin:auto;padding:24px;">
  <div style="background:#1c2b3f;padding:16px 24px;border-radius:8px 8px 0 0;display:flex;align-items:center;justify-content:space-between;">
    <h2 style="color:#fff;margin:0;font-size:18px;">📋 Open RAR Summary — Action Required</h2>
    <img src="https://www.danlaw.com/wp-content/uploads/2021/01/danlaw-logo-white.png" alt="Danlaw" style="height:28px;object-fit:contain;" />
  </div>
  <div style="border:1px solid #dde3eb;border-top:none;border-radius:0 0 8px 8px;padding:24px;">
    <p style="font-size:14px;margin-top:0;">
      This is a periodic reminder from <strong>Internal Rejection Management System</strong>. There are currently
      <strong>{count} open RAR(s)</strong> that require attention. Please log in to the Internal Rejection Management System
      → <strong>RAR Tracking</strong> tab to review and take corrective actions.
    </p>
    <table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:20px;table-layout:fixed;">
      <colgroup>
        <col style="width:80px;"><col style="width:85px;"><col style="width:100px;">
        <col style="width:130px;"><col style="width:130px;"><col style="width:65px;">
      </colgroup>
      <tr style="background:#1c2b3f;color:#fff;">
        <th style="text-align:left;padding:9px 10px;border:1px solid #243650;">RAR No.</th>
        <th style="text-align:left;padding:9px 10px;border:1px solid #243650;">Date</th>
        <th style="text-align:left;padding:9px 10px;border:1px solid #243650;">Customer</th>
        <th style="text-align:left;padding:9px 10px;border:1px solid #243650;">Product</th>
        <th style="text-align:left;padding:9px 10px;border:1px solid #243650;">Defect Mode</th>
        <th style="text-align:center;padding:9px 10px;border:1px solid #243650;">Category</th>
      </tr>{rows}
    </table>
    <p style="font-size:13px;color:#6b7a90;">Log in to Internal Rejection Management System → <strong>RAR Tracking</strong> tab and search by RAR No. to locate each form.</p>
    <hr style="border:none;border-top:1px solid #dde3eb;margin:20px 0;">
    <p style="font-size:11px;color:#9aabb6;margin:0;">Automated periodic reminder. Do not reply to this email.</p>
  </div>
</body></html>"""
    return subject, html


def _build_new_rar_email(rec, from_name):
    rno   = rec.get("rarNo","—");  date  = rec.get("date","—")
    cust  = rec.get("customer","—"); prod = rec.get("product","—")
    stage = rec.get("stage","—");  proc  = rec.get("process","—")
    cat   = rec.get("category","—"); defm = rec.get("defectMode","—")
    cause = rec.get("cause","—")
    subject = f"[Internal Rejection Management System] New Open RAR: {rno} — Immediate Action Required"
    html = f"""<html><body style="font-family:Arial,sans-serif;color:#1c2b3f;max-width:640px;margin:auto;padding:24px;">
  <div style="background:#1c2b3f;padding:16px 24px;border-radius:8px 8px 0 0;display:flex;align-items:center;justify-content:space-between;">
    <h2 style="color:#fff;margin:0;font-size:18px;">⚠ New Open RAR Raised — Action Required</h2>
    <img src="https://www.danlaw.com/wp-content/uploads/2021/01/danlaw-logo-white.png" alt="Danlaw" style="height:28px;object-fit:contain;" />
  </div>
  <div style="border:1px solid #dde3eb;border-top:none;border-radius:0 0 8px 8px;padding:24px;">
    <p style="font-size:14px;margin-top:0;">
      A new Rejection Analysis Report has been raised and is currently <strong>Open</strong>.
      Please log in to the Internal Rejection Management System → <strong>RAR Tracking</strong> tab
      to review, investigate the root cause, and initiate corrective actions.
    </p>
    <table style="width:100%;border-collapse:collapse;font-size:13px;margin-bottom:20px;">
      <tr style="background:#f6f8fb;"><th style="text-align:left;padding:8px 12px;border:1px solid #dde3eb;width:36%;">Field</th><th style="text-align:left;padding:8px 12px;border:1px solid #dde3eb;">Details</th></tr>
      <tr><td style="padding:8px 12px;border:1px solid #dde3eb;font-weight:600;">RAR No.</td><td style="padding:8px 12px;border:1px solid #dde3eb;font-weight:700;color:#2563a8;">{rno}</td></tr>
      <tr style="background:#f6f8fb;"><td style="padding:8px 12px;border:1px solid #dde3eb;font-weight:600;">Date</td><td style="padding:8px 12px;border:1px solid #dde3eb;">{date}</td></tr>
      <tr><td style="padding:8px 12px;border:1px solid #dde3eb;font-weight:600;">Customer</td><td style="padding:8px 12px;border:1px solid #dde3eb;">{cust}</td></tr>
      <tr style="background:#f6f8fb;"><td style="padding:8px 12px;border:1px solid #dde3eb;font-weight:600;">Product</td><td style="padding:8px 12px;border:1px solid #dde3eb;">{prod}</td></tr>
      <tr><td style="padding:8px 12px;border:1px solid #dde3eb;font-weight:600;">Stage</td><td style="padding:8px 12px;border:1px solid #dde3eb;">{stage}</td></tr>
      <tr style="background:#f6f8fb;"><td style="padding:8px 12px;border:1px solid #dde3eb;font-weight:600;">Process</td><td style="padding:8px 12px;border:1px solid #dde3eb;">{proc}</td></tr>
      <tr><td style="padding:8px 12px;border:1px solid #dde3eb;font-weight:600;">Category</td><td style="padding:8px 12px;border:1px solid #dde3eb;">{cat}</td></tr>
      <tr style="background:#f6f8fb;"><td style="padding:8px 12px;border:1px solid #dde3eb;font-weight:600;">Defect Mode</td><td style="padding:8px 12px;border:1px solid #dde3eb;">{defm}</td></tr>
      <tr><td style="padding:8px 12px;border:1px solid #dde3eb;font-weight:600;">Cause</td><td style="padding:8px 12px;border:1px solid #dde3eb;">{cause}</td></tr>
    </table>
    <p style="font-size:13px;color:#6b7a90;">➡ Log in → <strong>RAR Tracking</strong> tab → search RAR No. <strong>{rno}</strong>.</p>
    <hr style="border:none;border-top:1px solid #dde3eb;margin:20px 0;">
    <p style="font-size:11px;color:#9aabb6;margin:0;">Automated notification from Internal Rejection Management System. Do not reply.</p>
  </div>
</body></html>"""
    return subject, html


# ── Start ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    # Start the background scheduler (replaces Cloudflare Cron)
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(run_digest, "interval", minutes=10)
    scheduler.start()
    print(f"[RAR EMS] Server starting on port {PORT}")
    print(f"[RAR EMS] Database: {DB_PATH}")
    print(f"[RAR EMS] Email mode: {'SMTP' if USE_SMTP else 'Resend'}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
