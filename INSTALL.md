# Installing RentStuff

RentStuff is a small Flask + SQLite app. You can run it two ways: a local
Python environment (best for trying it out or developing) or Docker Compose
(best for hosting it somewhere). Pick one.

- [Requirements](#requirements)
- [Option A — Local (Python)](#option-a--local-python)
- [Option B — Docker Compose](#option-b--docker-compose)
- [Configuration](#configuration)
- [First run](#first-run)
- [Putting it behind a domain](#putting-it-behind-a-domain)
- [Backups](#backups)
- [Tests](#tests)
- [Troubleshooting](#troubleshooting)

---

## Requirements

- **Local:** Python 3.11 or newer.
- **Docker:** Docker with the Compose plugin (`docker compose`). No Python needed.

---

## Option A — Local (Python)

```bash
# 1. clone and enter
git clone <your-repo-url> rentstuff
cd rentstuff

# 2. virtual environment
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

# 3. dependencies
pip install -r requirements-dev.txt

# 4. environment
cp .env.example .env               # then edit .env (see Configuration below)

# 5. create the database
flask --app wsgi init-db

# 6. optional: load a few sample items
flask --app wsgi seed

# 7. run it
flask --app wsgi run --debug       # http://127.0.0.1:5000
```

The public catalog is at `/`; the admin is at `/admin`.

---

## Option B — Docker Compose

```bash
git clone <your-repo-url> rentstuff
cd rentstuff
cp .env.example .env               # set SECRET_KEY and an admin password (see below)

docker compose up --build          # serves on http://localhost:8000
```

The container creates the database automatically on start (idempotent) and
persists it in the `rentstuff-data` volume, so your data survives restarts and
rebuilds. To load sample items once it's up:

```bash
docker compose exec rentstuff flask --app wsgi seed
```

---

## Configuration

All configuration is via environment variables (read from `.env`).

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `SECRET_KEY` | **yes** | — | Signs sessions. Use a long random string. |
| `ADMIN_USERNAME` | no | `admin` | Admin login name. |
| `ADMIN_PASSWORD` | dev only | `changeme` | Plaintext admin password; the app hashes it at startup. Fine for local use. |
| `ADMIN_PASSWORD_HASH` | prod | — | A pre-computed password hash. Set this instead of `ADMIN_PASSWORD` in production. |
| `RENTSTUFF_DB` | no | `./instance/rentstuff.sqlite3` (local) / `/data/rentstuff.sqlite3` (Docker) | Path to the SQLite file. |
| `RENTSTUFF_UPLOADS` | no | `<db-dir>/uploads` | Where uploaded item photos are stored. Defaults next to the DB, so it persists on the same Docker volume. |

**Generate a `SECRET_KEY`:**

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

**Generate an `ADMIN_PASSWORD_HASH`** (do this for anything internet-facing, so a
plaintext password never sits in your environment):

```bash
python -c "from werkzeug.security import generate_password_hash as g; print(g('your-real-password'))"
```

Paste the result into `ADMIN_PASSWORD_HASH` and leave `ADMIN_PASSWORD` unset.

---

## First run

1. Start the app (Option A or B).
2. Visit `/admin` and log in with your `ADMIN_USERNAME` / password.
3. Add items (name, rate, deposit) under **items**, or run the `seed` command
   for sample data.
4. The public catalog at `/` shows active items; people request dates there, and
   requests show up under **bookings** in the admin for you to confirm and, later,
   mark paid.

---

## Putting it behind a domain

RentStuff listens on port `8000` in Docker (or `5000` in local dev). To serve it
on a real hostname over HTTPS, put it behind any reverse proxy you already run
(nginx, Caddy, Traefik, …): terminate TLS at the proxy and forward to the
container's port. RentStuff doesn't need to know its public URL.

---

## Backups

Everything lives in the single SQLite file (`RENTSTUFF_DB`). Back it up by
copying that file.

```bash
# local
cp instance/rentstuff.sqlite3 backup-$(date +%F).sqlite3

# docker (from the named volume)
docker compose cp rentstuff:/data/rentstuff.sqlite3 ./backup-$(date +%F).sqlite3
```

---

## Tests

```bash
pip install -r requirements-dev.txt
pytest -q
```

---

## Troubleshooting

- **`RuntimeError: SECRET_KEY` / sessions not working** — set `SECRET_KEY` in
  `.env`.
- **Can't log in** — confirm `ADMIN_USERNAME`, and that you set either
  `ADMIN_PASSWORD` or `ADMIN_PASSWORD_HASH` (not a stale hash from a different
  password).
- **Database changes don't stick in Docker** — make sure the `rentstuff-data`
  volume is intact; deleting it wipes the database.
- **Port already in use** — change the published port in `docker-compose.yml`
  (`"8000:8000"` → e.g. `"8080:8000"`).
