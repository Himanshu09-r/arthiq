# ARTHIQ login + Neon PostgreSQL deployment update

This update adds a single-owner username/password login and switches SQLAlchemy to support Neon PostgreSQL while retaining local SQLite for development.

## 1. Files changed / added

- `app/api/auth.py` — login, session check, logout endpoints.
- `app/auth.py` — authentication dependency used to protect backend routes.
- `app/api/main.py` — signed session cookie and protection for existing API routers/endpoints.
- `app/db/session.py` — SQLite/PostgreSQL URL handling and dialect-specific engine options.
- `app/db/migrate.py` — portable SQLAlchemy schema inspection and migration recording for SQLite/PostgreSQL.
- `migrate_sqlite_to_postgres.py` — one-time copy of existing SQLite rows to an empty Neon database.
- `web/login.html`, `web/auth.js` — login screen and shared login guard/logout action.
- `web/index.html`, `web/customers.html`, `web/dashboard.html`, `web/insights.html`, `web/inventory.html`, `web/console.html` — load the shared auth guard.
- `requirements.txt`, `.env.example` — PostgreSQL driver and signed-cookie dependency/configuration.

## 2. Create Neon database

1. Create a project at https://neon.tech/.
2. Create/select a database (e.g. `arthiq`).
3. Copy the connection string from Neon. It should be a PostgreSQL URL. Keep it private.
4. Do not put the connection string in GitHub or in frontend/Vercel environment variables.

## 3. Configure Render environment variables

In Render → ARTHIQ backend service → Environment, add/update:

- `DATABASE_URL` = Neon PostgreSQL connection string from Neon.
- `ARTHIQ_LOGIN_USERNAME` = your chosen login username.
- `ARTHIQ_LOGIN_PASSWORD` = a long, unique password (not the example value).
- `SESSION_SECRET` = a cryptographically random secret of at least 32 bytes.
- `COOKIE_SECURE` = `true`.

Keep all existing Gnani/Sarvam variables already configured on Render. Do not move provider keys to Vercel. Do not upload `.env` to GitHub.

Generate a session secret locally with Python:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## 4. Preserve existing SQLite data (important)

The SQLite-to-Neon script copies rows from a local SQLite file into an **empty** Neon database. It refuses to copy if target tables already contain records.

1. Obtain the actual current `arthiq.db` file from the environment where the live shop data currently exists. Do not assume the copy inside an old ZIP is current.
2. Keep an untouched backup copy.
3. On a machine with this project and Python dependencies installed, set:

```bash
# Windows PowerShell example; adjust the actual SQLite file path
$env:SOURCE_DATABASE_URL = "sqlite:///C:/full/path/to/arthiq.db"
$env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DB?sslmode=require"
python -m pip install -r requirements.txt
python migrate_sqlite_to_postgres.py
```

Use the Neon connection string exactly as Neon provides it. The script normalizes `postgresql://` / `postgres://` to psycopg 3. It creates the current schema and copies table rows in foreign-key order. Keep the original SQLite file unchanged until the Neon app is verified.

**Do not redeploy with the Neon `DATABASE_URL` until you have decided whether live SQLite data needs to be copied.** If the live database exists only on Render's temporary filesystem and you do not have a copy, stop and export/recover it before switching. The project ZIP does not contain your live database file.

## 5. GitHub upload

Upload/replace the files listed in section 1, preserving their folder paths. In particular:

- `app/api/auth.py` goes inside `app/api/`.
- `app/auth.py` goes inside `app/`.
- `web/login.html` and `web/auth.js` go inside `web/`.
- `migrate_sqlite_to_postgres.py` and `NEON_LOGIN_DEPLOYMENT.md` go in the repository root.

Do not upload `.env`, `arthiq.db`, API keys, or any Neon connection string.

## 6. Vercel routing

The frontend already calls backend endpoints using same-origin relative paths (for example `/customers`). The existing Vercel rewrite/proxy must also forward `/auth/*` to the Render backend, in addition to all the existing API paths. If the current rewrite is a catch-all that forwards every non-static/backend request to Render, no change is needed. Do not replace your existing `vercel.json` blindly; preserve its current frontend/static configuration.

Set Vercel Root Directory to the existing `web` directory as before. `login.html` and `auth.js` are static files in that directory.

## 7. Render deployment

Keep the existing service build/start commands:

```bash
pip install -r requirements.txt
uvicorn app.api.main:app --host 0.0.0.0 --port $PORT
```

Deploy only after Neon data migration (if required) and Render environment variables are ready. Check Render logs for startup/database errors.

## 8. Verify after deployment

1. Open `https://YOUR-VERCEL-DOMAIN/login.html`.
2. Sign in with the username/password set on Render.
3. Confirm the dashboard opens and the floating **Log out** button is visible.
4. Log out; confirm dashboard routes return to login.
5. Sign in again; verify customers, ledger and stock records.
6. Add a harmless test record, refresh, and verify it remains.
7. In Neon SQL Editor, inspect tables/row counts if needed.

The app currently has one configured owner login shared for this deployment; this is not a multi-user shop-account/role system. Password reset is performed by changing `ARTHIQ_LOGIN_PASSWORD` in Render.
