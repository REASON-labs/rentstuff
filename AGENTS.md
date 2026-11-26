# AGENTS.md
RentStuff: a small self-hosted rental catalog for lending out gear. People browse and request dates; the admin tracks bookings and who owes what. No card processing.

## Stack
- Python 3.12 or newer (3.11 fails at import), `Flask>=3.0`, `Flask-WTF>=1.2` (CSRF), `gunicorn>=21.0`, `python-dotenv>=1.0`, `Pillow>=10.2`, `pillow-heif>=0.16`.
- SQLite, server-rendered Jinja templates, session-based admin login.
- Tests: `pytest>=8.0`. CI: GitHub Actions on Python 3.12.
- Runs as one Docker Compose service (Gunicorn, 2 workers, port 8000) with the database and uploads in a volume.

## Commands
- Install: `pip install -r requirements-dev.txt`
- Create the schema (idempotent): `flask --app wsgi init-db`
- Sample items (optional): `flask --app wsgi seed`
- Dev: `flask --app wsgi run --debug`
- Test: `pytest -q`
- Docker: `docker compose up --build`
- Sweep orphan photos: `flask --app wsgi prune-uploads --dry-run`, then without `--dry-run`

## Key files
- `app/__init__.py` - app factory, startup checks, CLI commands (`init-db`, `seed`, `prune-uploads`).
- `app/availability.py` - pure booking logic (overlap, quote, outstanding); no Flask, no database.
- `app/models.py`, `app/db.py`, `app/schema.sql` - SQLite data access and schema.
- `app/routes/public.py`, `app/routes/admin.py` - catalog and reserve form; admin dashboard, items, bookings.
- `app/hardening.py`, `app/limits.py` - form stamp, honeypots, input checks; rate limits and the mail budget.
- `app/mail.py` - the only place mail leaves; validates every recipient.
- `app/config.py` - core settings from env vars; `app/__init__.py`, `app/mail.py` and `app/limits.py` read a few more.
- `tests/test_availability.py` - the suite that matters most; `tests/test_app.py` covers the routes.

## Conventions
- Dates are half-open `[start, end)`: the return day is free again. Only `confirmed` bookings and blackout windows block new requests.
- Keep `app/availability.py` free of Flask and database imports.
- Guards on outgoing mail belong inside `send_email`, not at the call sites.
- Logs are one JSON line per outcome on stdout; never log renter names, contacts or note text.
- Update steps for a running instance are in `DEPLOY.md`; first-time setup is in `INSTALL.md`.

## Gotchas
- The app exits at startup if `SECRET_KEY` is unset or the admin password is still the default. Set `SECRET_KEY` and `ADMIN_PASSWORD_HASH` (or `ADMIN_PASSWORD`).
- A variable in `.env` reaches the container only if `docker-compose.yml` lists it under `environment`.
- `TRUSTED_PROXIES` must equal the real number of reverse proxies: too low and all visitors share one rate limit, too high and clients can forge their address.
- Rate-limit and mail-budget counters are in memory per Gunicorn worker; more workers means looser limits (`app/limits.py`).
- Mail is optional: without `MAILGUN_API_KEY` and `MAILGUN_DOMAIN`, sending does nothing.
- Never commit `.env`, `*.sqlite3` or `instance/` (git-ignored). Uploads sit next to the database (`RENTSTUFF_DB`, `RENTSTUFF_UPLOADS`).
- A dependency change needs an image rebuild, not just a pull.
