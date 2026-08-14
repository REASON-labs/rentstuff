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
    try:
        img = Image.open(file_storage.stream)
        img = img.convert("RGB")
        img.thumbnail((1400, 1400))          # cap dimensions, keep aspect
        img.save(dest, "WEBP", quality=82, method=6)
    except Exception:
        return None
    return "uploads/" + name
