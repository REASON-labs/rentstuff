# RentStuff

A dead-simple rental catalog for lending out gear — a bike, a tent, a camera, a
cooler, whatever you own. People browse what's available,
request dates, and you track who has what and what they owe.

> v1 is **billing tracking only**: list items, take reservation requests, catch
> double-bookings, and keep a ledger of who owes what. No card processing —
> mark payments as they land (cash, transfer, an invoice number). Stripe and
> external invoicing are designed in as clean seams, not built.

## Stack

Flask + SQLite, server-rendered Jinja, Flask-WTF CSRF, session-based admin auth,
pytest, GitHub Actions CI, Docker Compose. MIT. Runtime deps are just Flask,
Flask-WTF, and gunicorn.

## Quickstart

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env          # set SECRET_KEY; ADMIN_PASSWORD defaults to 'changeme'
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
overlap / quote / outstanding logic, tested with no DB.

## Docker

```bash
docker compose up --build   # serves on :8000, SQLite persisted in a volume
```

Set `SECRET_KEY` (and ideally a real `ADMIN_PASSWORD_HASH`) in your `.env` first.

## How it fits together

- `app/availability.py` — pure core: `intervals_overlap`, `find_conflicts`,
  `quote_amount`, `outstanding_by_renter`. No Flask, no DB.
- `app/models.py` — thin sqlite data access + per-item availability status.
- `app/routes/public.py` — the catalog and the reservation request form.
- `app/routes/admin.py` — dashboard (outstanding rollup, returns due), item CRUD,
  booking lifecycle (confirm → returned → cancelled) and mark-paid.

Dates are half-open `[start, end)` — the return day is when the item is free
again, so back-to-back reservations that touch don't conflict. Only `confirmed`
bookings (plus blackout windows) block new requests.

## Design

A warm, industrial catalog look — `app/static/css/rentstuff.css`. Each item
shows a photo if it has one, otherwise a line-diagram. Admins can upload a
photo per item (re-encoded to WebP, capped at 1400px; iPhone HEIC supported)
or pick from ten bundled defaults in `app/static/img/defaults/`. Diagrams live
as SVG partials in `app/templates/diagrams/<slug>.svg`, with `_default.svg` as
the fallback. Uploads are stored in `UPLOAD_DIR` (next to the DB) and served
via the `/media/<file>` route.

### Seams (stubs, not built)

- **External invoicing.** Mark-paid stores `payment_method` + `payment_ref`
  (e.g. an invoice number), so pushing a booking to an invoicing API later is a
  single service module.
- **Stripe.** The `payment_method` / `payment_ref` / `paid_at` columns already
  exist — adding a Payment Link or Checkout session later just fills them and
  flips `is_paid` via a webhook.

## License

MIT — see [LICENSE](LICENSE).
