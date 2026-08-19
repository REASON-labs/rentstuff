"""Item image handling: resolve a stored photo_path to a URL, list the bundled
default images, and safely save an uploaded photo (re-encoded to strip metadata
and cap dimensions)."""
import os
import uuid

from flask import current_app, url_for

# Bundled placeholder defaults (swap the SVGs in static/img/defaults/ for real art).
DEFAULT_IMAGES = [f"img/defaults/{i:02d}.svg" for i in range(1, 11)]

ALLOWED_EXT = {"jpg", "jpeg", "png", "webp", "gif", "heic", "heif"}


def photo_src(path):
    """Turn a stored photo_path into a usable URL. Uploads are served through the
    media route; everything else is treated as a static asset (the defaults)."""
    if not path:
        return None
    if path.startswith("uploads/"):
        return url_for("public.media", filename=path[len("uploads/"):])
    return url_for("static", filename=path)


def _ext_ok(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT


def save_upload(file_storage):
    """Validate + normalize an uploaded image. Returns 'uploads/<name>' or None."""
    if not file_storage or not file_storage.filename or not _ext_ok(file_storage.filename):
        return None

    from PIL import Image
    try:  # optional: lets iPhone HEIC/HEIF uploads work
        import pillow_heif
        pillow_heif.register_heif_opener()
    except Exception:
        pass

    upload_dir = current_app.config["UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    name = uuid.uuid4().hex + ".webp"
    dest = os.path.join(upload_dir, name)
    # Re-encoding through Pillow already means the stored file is a real image
    # whatever the uploader called it — but the decode itself is the exposure.
    # Image.open only reads the header; convert() below is what allocates the
    # full bitmap, and thumbnail() caps the output, not the input. A 100KB PNG
    # can declare 60000x60000 and expand to tens of gigabytes before either
    # line runs, so the dimensions have to be checked while it's still lazy.
    max_pixels = current_app.config.get("MAX_IMAGE_PIXELS", 50_000_000)
    try:
        img = Image.open(file_storage.stream)
        width, height = img.size
        if width * height > max_pixels:
            current_app.logger.warning(
                "rejected an upload declaring %dx%d pixels", width, height)
            return None
        img = img.convert("RGB")
        img.thumbnail((1400, 1400))          # cap dimensions, keep aspect
        img.save(dest, "WEBP", quality=82, method=6)
    except Exception:
        return None
    return "uploads/" + name


def discard_upload(path):
    """Delete an upload the database no longer points at. Returns True if a file
    was actually removed.

    Only ever touches 'uploads/…' paths — a default image like
    'img/defaults/03.svg' is bundled and shared between items, so it must
    survive. basename() strips any directory component, so a crafted path can't
    escape the upload directory. Call this *after* the DB write succeeds: a
    missing file is cosmetic, a row pointing at a deleted file is a broken page.
    """
    if not path or not path.startswith("uploads/"):
        return False
    name = os.path.basename(path[len("uploads/"):])
    if not name:
        return False
    full = os.path.join(current_app.config["UPLOAD_DIR"], name)
    try:
        os.remove(full)
        return True
    except FileNotFoundError:
        return False
    except OSError:
        current_app.logger.exception("could not remove upload %s", full)
        return False


# save_upload() writes the file before the route commits the row, so a file
# that new may be referenced by a row that doesn't exist yet. Leave anything
# younger than this alone; the next sweep will catch it if it really is junk.
PRUNE_MIN_AGE_SECONDS = 15 * 60


def prune_uploads(dry_run=False):
    """Find upload files no item references and delete them, returning their
    names. This is the catch-up sweep for orphans left behind before deletion
    was wired in; discard_upload keeps things tidy from here on."""
    import time

    from . import models

    referenced = {
        os.path.basename(p[len("uploads/"):])
        for p in models.all_photo_paths() if p.startswith("uploads/")
    }
    upload_dir = current_app.config["UPLOAD_DIR"]
    if not os.path.isdir(upload_dir):
        return []

    cutoff = time.time() - PRUNE_MIN_AGE_SECONDS
    orphans = []
    for name in sorted(os.listdir(upload_dir)):
        full = os.path.join(upload_dir, name)
        if name in referenced or not os.path.isfile(full):
            continue
        try:
            if os.path.getmtime(full) > cutoff:
                continue        # too new to judge — an in-flight upload
        except OSError:
            continue
        orphans.append(name)
        if not dry_run:
            try:
                os.remove(full)
            except OSError:
                current_app.logger.exception("could not remove upload %s", full)
    return orphans
