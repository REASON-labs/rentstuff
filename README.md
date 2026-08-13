# RentStuff

A dead-simple loaner/rental tracker for lending gear to friends and family. Sibling project to
**FreeStuff** (the giveaway board); same stack, same conventions.

> v1 is **billing tracking only**: list items, take booking requests, catch
> double-bookings, and keep a ledger of who owes what. No card processing.
> Real invoicing is handed off to Zoho; Stripe is a later staple-on. Both are
> designed in as clean seams, not built yet.

## Stack

Flask + SQLite, server-rendered Jinja, Flask-WTF CSRF, session-based admin auth,
pytest, GitHub Actions CI, Docker Compose. MIT. Runtime deps are just Flask,
Flask-WTF, and gunicorn — nothing exotic.

## Quickstart (local)

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env          # set SECRET_KEY; ADMIN_PASSWORD defaults to 'changeme'
export FLASK_APP=wsgi         # Windows Git Bash: same; PowerShell: $env:FLASK_APP="wsgi"

flask --app wsgi init-db      # create the SQLite schema (idempotent)
flask --app wsgi seed         # optional: a few sample items
flask --app wsgi run --debug  # http://127.0.0.1:5000
```

Admin lives at `/admin` (log in with `ADMIN_USERNAME` / `ADMIN_PASSWORD`).

## Run tests

```bash
pytest -q
```

The suite that matters is `tests/test_availability.py` — the pure
overlap/quote/outstanding logic, tested with no DB.

## Docker

```bash
docker compose up --build
# serves on :8000, SQLite persisted in the rentstuff-data volume
```

Set `SECRET_KEY` (and ideally a real `ADMIN_PASSWORD_HASH`) in your `.env` first.

## How it fits together

- `app/availability.py` — **pure core**: `intervals_overlap`, `find_conflicts`,
  `quote_amount`, `outstanding_by_renter`. No Flask, no DB. This is the tested part.
- `app/models.py` — thin sqlite data access.
- `app/routes/public.py` — item list + the request form (creates a `requested` booking).
- `app/routes/admin.py` — dashboard (outstanding rollup, returns due), item CRUD,
  booking lifecycle (confirm → returned → cancelled) and mark-paid.

### Booking model

Dates are half-open `[start, end)` — the return day is when the item is free
again, so back-to-back bookings that touch don't conflict. Only `confirmed`
bookings (plus blackout windows) block new requests; `requested` ones are shown
for review but don't hard-block.

### The seams (v1 = stubs, not built)

- **Zoho invoicing.** Mark-paid already stores `payment_method='zoho'` +
  `payment_ref=<invoice #>`. Later, a single `zoho.py` with one
  `create_invoice(booking)` function (POST to the Zoho Invoice REST API) is the
  whole integration — nothing else changes.
- **Stripe.** The `payment_method` / `payment_ref` / `paid_at` columns already
  exist, so adding a Payment Link or Checkout session later just fills them and
  flips `is_paid` via a webhook. No schema churn; split payments into their own
  table only if partial payments ever arrive.

## Deploy

Built to run on the Hetzner box behind `rentstuff.jaybb.com` (reverse proxy),
same pattern as the other self-hosted apps. jaybb.com just links to it.

## License

MIT — see [LICENSE](LICENSE).
