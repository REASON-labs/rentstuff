import os

from dotenv import load_dotenv

load_dotenv()  # read .env if present (no-op otherwise)

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    DATABASE = os.environ.get(
        "RENTSTUFF_DB", os.path.join(_BASE, "instance", "rentstuff.sqlite3")
    )
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    # Prefer a pre-computed werkzeug hash in production. If empty, the app hashes
    # ADMIN_PASSWORD (default 'changeme') at startup — fine for local dev only.
    ADMIN_PASSWORD_HASH = os.environ.get("ADMIN_PASSWORD_HASH", "")
    WTF_CSRF_ENABLED = True
