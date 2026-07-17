# RAR EMS — 100% Cloudflare (Free Forever)

Everything on one platform. One GitHub repo, one push deploys both
the frontend and the backend automatically. No Render, no Koyeb,
no MongoDB Atlas needed.

```
rar-ems/
├── frontend/         ← Cloudflare Pages serves this (static HTML)
│   └── index.html
├── worker/           ← Cloudflare Worker runs this (Python API)
│   └── entry.py
├── wrangler.toml     ← Worker config (you fill in your D1 database ID)
├── schema.sql        ← Run once to create the D1 table
├── .gitignore
└── README.md
```

## Free tier limits (more than enough for a small team)

| Service | Free allowance |
|---|---|
| Cloudflare Pages | Unlimited bandwidth, 500 builds/month |
| Cloudflare Workers | 100,000 requests/day |
| Cloudflare D1 | 5 GB storage, 5M reads + writes/month |

A team of 5 people with the 30s polling interval uses roughly
~14,400 Worker requests/day — well inside the 100K/day free limit.

---

## One-time setup (do this once, never again)

### Step 1 — Push this repo to GitHub

1. Go to github.com → New repository → name it `rar-ems` → Private
   → do NOT tick "Add README" → Create repository
2. On the next page click "uploading an existing file"
3. Drag everything from this folder into the GitHub upload area
4. Click Commit changes
5. Confirm you see frontend/, worker/, wrangler.toml etc. in the repo

---

### Step 2 — Create the D1 database

1. Go to cloudflare.com → sign up free (email + password, no card)
2. In the left sidebar: Storage & Databases → D1 SQL Database → Create
3. Name it exactly: `rar-ems-db` → click Create
4. You'll see a database ID — copy it (looks like: a1b2c3d4-xxxx-xxxx-xxxx-xxxxxxxxxxxx)
5. In the D1 page, click your new database → click the "Console" tab
6. Paste this and click Run:

   CREATE TABLE IF NOT EXISTS app_state (
       key   TEXT PRIMARY KEY,
       value TEXT NOT NULL
   );

   You should see "success" — table is created.

---

### Step 3 — Deploy the Worker

1. In Cloudflare dashboard → Workers & Pages → Create → Worker
2. Name it exactly: `rar-ems-worker` → Deploy (ignore the default code)
3. After deploying, go to the Worker → Settings → Bindings
4. Click Add → D1 Database
   - Variable name: DB
   - D1 database: rar-ems-db
   - Save
5. Go to Settings → Variables and Secrets → add these if needed:
   - ALLOWED_ORIGINS → (leave blank for now, fill after Step 5)
   - APP_SHARED_KEY  → (leave blank unless you want a password)
6. Go to the Worker → Deployments tab → note your Worker URL:
   https://rar-ems-worker.YOUR-SUBDOMAIN.workers.dev

Test it: open that URL + /healthz in your browser
→ should return {"ok": true}

---

### Step 4 — Update frontend with your Worker URL

1. In your GitHub repo, click frontend/index.html → pencil icon to edit
2. Find this near line 11 (Ctrl+F for RAR_API_BASE):

   window.RAR_API_BASE = "https://rar-ems-worker.YOUR-SUBDOMAIN.workers.dev";

3. Replace YOUR-SUBDOMAIN with your actual subdomain from Step 3
4. Scroll down → Commit changes

---

### Step 5 — Deploy the frontend on Cloudflare Pages

1. Cloudflare dashboard → Workers & Pages → Create → Pages
2. Connect to Git → authorize GitHub → select your rar-ems repo
3. Build settings:
   - Framework preset: None
   - Build command: (leave empty)
   - Build output directory: frontend
4. Save and Deploy → wait ~1 minute
5. Note your Pages URL: https://rar-ems.pages.dev (or similar)

---

### Step 6 — Connect Pages ↔ Worker (CORS lock)

1. Cloudflare dashboard → Workers & Pages → rar-ems-worker → Settings
2. Variables and Secrets → set ALLOWED_ORIGINS to your Pages URL:
   https://rar-ems.pages.dev
   (no trailing slash, include https://)
3. Save → Worker redeploys in ~30 seconds

---

### Step 7 — Verify

1. Open your Pages URL (https://rar-ems.pages.dev)
2. Bottom-right badge should show: ☁ Cloud sync: ON
3. Open the same URL on a second device
4. Save a change on one → appears on the other within ~30 seconds

---

## Making changes going forward

Every future change is just:
1. Go to the file in GitHub → click the pencil icon → edit → Commit changes
2. Both the Worker and Pages redeploy automatically within 2-3 minutes

| What to change | Which file | Effect after commit |
|---|---|---|
| UI / layout | frontend/index.html | Pages redeploys |
| API logic | worker/entry.py | Worker redeploys |
| Both at once | Edit both → one commit | Both redeploy |

No Git Bash, no terminal, no dashboards — just edit on GitHub and push.

---

## If something stops working

- Check Workers & Pages dashboard → your Worker → Logs tab for errors
- Check D1 → rar-ems-db → Console tab: run `SELECT * FROM app_state;`
  to confirm data is there
- Make sure ALLOWED_ORIGINS exactly matches your Pages URL (no trailing slash)
