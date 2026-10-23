import os

from dotenv import load_dotenv

load_dotenv()  # read .env if present (no-op otherwise)

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "")
    DATABASE = os.environ.get(
        "RENTSTUFF_DB", os.path.join(_BASE, "instance", "rentstuff.sqlite3")
    )
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    # Prefer a pre-computed werkzeug hash in production. If empty, the app hashes
    # ADMIN_PASSWORD (default 'changeme') at startup — fine for local dev only.
    ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")
    WTF_CSRF_ENABLED = True
    # Uploaded item photos live next to the DB, so they persist on the same
    # volume in Docker. Override with RENTSTUFF_UPLOADS if you like.
    UPLOAD_DIR = os.environ.get("RENTSTUFF_UPLOADS") or os.path.join(
        os.path.dirname(DATABASE), "uploads")
    MAX_CONTENT_LENGTH = 8 * 1024 * 1024  # 8 MB upload cap

    # --- session cookie hardening ------------------------------------------
    # SameSite=Lax blocks the cross-site form POSTs that CSRF depends on; the
    # Flask-WTF token is the belt to its braces. Secure is opt-in because the
    # cookie would otherwise never be set over plain HTTP in local dev.
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SECURE_COOKIES", "") == "1"

    # --- anti-abuse ---------------------------------------------------------
    # How many reverse proxies sit in front of the app. Get this right: too low
    # and every visitor appears to share the proxy's address, so one spammer
    # rate-limits the whole site; too high and a client can forge
    # X-Forwarded-For and skip the limiter. 0 = exposed directly.
    TRUSTED_PROXIES = int(os.environ.get("TRUSTED_PROXIES", "0"))
    # Turn away renter email addresses on known throwaway-mail domains.
    BLOCK_DISPOSABLE_EMAIL = os.environ.get("BLOCK_DISPOSABLE_EMAIL", "") == "1"
    # Refuse to decode images above this pixel count (decompression-bomb guard).
    MAX_IMAGE_PIXELS = int(os.environ.get("MAX_IMAGE_PIXELS", str(50_000_000)))
