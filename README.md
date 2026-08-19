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

Requires **Python 3.12+** (3.11 fails at import — PEP 701 f-strings).

```bash
python3.12 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt

cp .env.example .env          # set SECRET_KEY; ADMIN_PASSWORD defaults to 'changeme'
flask --app wsgi init-db      # create the SQLite schema (idempotent)
flask --app wsgi seed         # optional: a few sample items
flask --app wsgi run --debug  # http://127.0.0.1:5000
```

Admin lives at `/admin` (log in with `ADMIN_USERNAME` / `ADMIN_PASSWORD`).
`GET /healthz` is an unauthenticated probe that returns `{"status":"ok"}`
when the app can read its database, and 503 when it can't.

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

## Anti-abuse

The public reserve form is the one place strangers can write to the database —
and, because RentStuff sends email, the one place they can make it send mail to
an address they chose. On 2026-08-18 this form took 21 near-identical bookings
in 20 seconds. It is now defended in layers; none is strong alone, but together
they stop that pattern without putting a CAPTCHA in front of your friends.

| Layer | What it does |
|---|---|
| CSRF token | Flask-WTF, on every form. |
| Signed form stamp | Hidden, signed issue-time. Rejects submissions faster than 3s (scripted) or older than 6h (scraped and replayed). |
| Honeypots | Two off-screen decoy fields. Anything that fills one is automated. |
| Rate limits | Per IP: 3 requests / 2 min, 10 / hour, and 2 / hour on any one item. |
| Field validation | At least one real way to reach you (email or phone); links rejected in names; control characters stripped; server-side past-date and max-length checks. |
| Duplicate detection | A repeat request for the same item and dates is absorbed, not queued twice. |
| **Recipient validation** | **Every outbound address is checked inside `send_email`, so no notification path can be turned into a relay for mailing strangers.** |
| **Mail budget** | **A hard cap on how much mail any one address can cause us to send per day.** |
| Login throttle | 5 failed passwords per IP per 15 minutes, then HTTP 429. |
| Structured logs | One JSON line per outcome on stdout, same format as FreeStuff. |

The two bold rows are RentStuff-specific — they are Category 4 of the family
hardening spec, which FreeStuff (no mail layer) doesn't need. They live in
`send_email` rather than at the form on purpose: the reserve form isn't the only
thing that creates bookings, and a guard at the single point where mail actually
leaves is one no future call site can forget.

Deliberately **not** included: a CAPTCHA (an external script on every page plus
a real accessibility cost, for a site a few dozen people use) and gibberish or
entropy scoring on names — it flags real names like *Szczepanski* far more often
than it catches a bot that can just as easily generate *Sarah Miller*.

### Configuration

| Variable | Default | Purpose |
|---|---|---|
| `TRUSTED_PROXIES` | `0` | How many reverse proxies sit in front of the app. **Set this to `1` behind Traefik.** |
| `SECURE_COOKIES` | off | Set to `1` when serving over HTTPS. |
| `BLOCK_DISPOSABLE_EMAIL` | off | Set to `1` to turn away known throwaway-mail domains. |
| `MAIL_PER_ADDRESS_PER_DAY` | `12` | Cap on notifications sent to any one address per day. |

`TRUSTED_PROXIES` matters more than it looks: leave it at `0` behind Traefik and
every visitor appears to the app as the proxy's own address, so the rate limiter
treats the whole site as one client and the first spammer locks everyone out.
Set it higher than the real number of proxies and a client can forge
`X-Forwarded-For` to skip the limiter entirely.

### Watching for trouble

```bash
docker compose logs rentstuff | grep booking_rejected | jq -r .reason | sort | uniq -c
docker compose logs rentstuff | grep rate_limited    | jq -r .ip     | sort | uniq -c | sort -rn
```

No renter name, contact, email or note text is ever logged — addresses appear
only as a truncated hash, enough to correlate a repeat offender without the log
becoming a second copy of the booking table.

### A note on scale

The rate limiter and the mail budget hold their counters in process memory
rather than Redis, which keeps the deploy at one container. The tradeoff: each
gunicorn worker counts separately, so with 2 workers a client gets roughly twice
the listed allowance. The thresholds are set with that in mind; if you raise
`--workers`, lower them in `app/limits.py` to match.

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
