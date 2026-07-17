-- RAR EMS — D1 database schema
-- Run this once in the Cloudflare dashboard → D1 → your database → Console
-- (or via: npx wrangler d1 execute rar-ems-db --file=schema.sql)

CREATE TABLE IF NOT EXISTS app_state (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
