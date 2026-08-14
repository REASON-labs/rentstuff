# Deploying RentStuff updates

Steps for pushing a code change to a **running** RentStuff instance. For a
first-time setup, see [INSTALL.md](INSTALL.md) instead.

The flow is the same for every update; where a step only matters for *this*
round of changes (photo uploads, dark-mode toggle, auto-slug), it's called out.

---

## 1. Update and verify locally

From your working copy, with the new files in place:

```bash
pip install -r requirements-dev.txt   # picks up any new deps
pytest -q                             # should be all green
```

> **This update adds dependencies** — `Pillow` and `pillow-heif` (image
> processing + iPhone HEIC support). A plain `git pull` on the server is not
> enough; the deploy step below rebuilds so they get installed.

## 2. Commit and push

```bash
git add -A
git commit -m "Images, dark-mode icon toggle, auto slug, tagline"
git push
```

CI (`.github/workflows/ci.yml`) runs the test suite on push.

## 3. Deploy on the server

### Docker Compose (recommended)

```bash
cd /path/to/rentstuff
git pull
docker compose up -d --build          # --build is required when deps change
```

- The container entrypoint runs `flask --app wsgi init-db` on start. It's
  idempotent (`CREATE TABLE IF NOT EXISTS`), so it's safe every deploy. **This
  update has no schema change**, so nothing migrates.
- **Data survives the rebuild.** The SQLite database *and* uploaded photos both
  live on the `rentstuff-data` volume (`UPLOAD_DIR` defaults next to the DB), so
  rebuilding the image doesn't touch them. No compose change is needed for the
  new upload feature.

### Plain Python (systemd / manual)

```bash
cd /path/to/rentstuff
git pull
source .venv/bin/activate
pip install -r requirements.txt        # installs Pillow + pillow-heif
flask --app wsgi init-db               # idempotent
# restart your process manager, e.g.:
sudo systemctl restart rentstuff
```

## 4. Smoke-test the live site

```bash
curl -I https://your-host/            # 200
```

Then in a browser: the catalog shows **"Rent our stuff."** and the small
sun/moon toggle flips light/dark; log into `/admin`, add an item, and confirm
you can either upload a photo or pick a default and it renders on the catalog.

---

## Environment

No new **required** variables this update. Optional:

| Variable | Purpose |
|---|---|
| `RENTSTUFF_UPLOADS` | Relocate uploaded photos. Defaults to `<db-dir>/uploads`, which rides the Docker volume automatically. |

(Full variable reference is in [INSTALL.md](INSTALL.md#configuration).)

## Rollback

Redeploy the previous commit (or image tag) and restart:

```bash
git revert <bad-commit> && git push        # or: git checkout <previous-tag>
docker compose up -d --build
```

The database and uploaded photos are on the volume and are left untouched by a
rollback, so no data is lost.
