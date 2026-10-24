import os

import click
from flask import Flask, request
from flask_wtf import CSRFProtect
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash

from . import db, hardening
from .config import Config
from .photos import photo_src

csrf = CSRFProtect()


def create_app(config_object=Config):
    app = Flask(__name__)
    app.config.from_object(config_object)

    os.makedirs(os.path.dirname(app.config["DATABASE"]), exist_ok=True)
    os.makedirs(app.config["UPLOAD_DIR"], exist_ok=True)
    app.jinja_env.globals["photo_src"] = photo_src

    # Resolve an admin password hash if only a plaintext dev password was given.
    if not app.config.get("ADMIN_PASSWORD_HASH"):
        plaintext = os.environ.get("ADMIN_PASSWORD", "changeme")
        app.config["ADMIN_PASSWORD_HASH"] = generate_password_hash(plaintext)

    # Behind a proxy, remote_addr is the proxy's address unless we say so — and
    # the rate limiter is only as good as the address it keys on.
    proxies = app.config.get("TRUSTED_PROXIES", 0)
    if proxies > 0:
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=proxies, x_proto=proxies)

    csrf.init_app(app)
    db.init_app(app)

    from .limits import form_stamp
    from .availability import BOOKING_TRANSITIONS
    app.jinja_env.globals["form_stamp"] = form_stamp
    app.jinja_env.globals["honeypot_fields"] = hardening.HONEYPOT_FIELDS
    app.jinja_env.globals["BOOKING_TRANSITIONS"] = BOOKING_TRANSITIONS

    @app.after_request
    def security_headers(response):
        """Cheap, universally-safe response headers.

        CSP is kept minimal: only the /media/ path gets a strict sandbox policy.
        The dark-mode pre-paint script in base.html requires inline JS, so a
        strict policy needs a per-request nonce first (tracked as a nice-to-have).
        """
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy",
                                    "strict-origin-when-cross-origin")
        response.headers.setdefault(
            "Permissions-Policy",
            "geolocation=(), camera=(), microphone=(), interest-cohort=()")
        # Uploaded photos are attacker-influenced bytes served from our own
        # origin. nosniff plus a hard sandbox means that even if a browser were
        # talked into treating one as HTML, it couldn't execute in our origin.
        if request.path.startswith("/media/"):
            response.headers["Content-Security-Policy"] = "sandbox; default-src 'none'"
        # HSTS: force HTTPS for one year, preloading. Not set in dev (no SECURE_COOKIES).
        if os.environ.get("SECURE_COOKIES") == "1":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response

    from . import auth
    from .routes import admin, public

    app.register_blueprint(public.bp)
    app.register_blueprint(auth.bp)
    app.register_blueprint(admin.bp, url_prefix="/admin")

    @app.cli.command("init-db")
    def init_db_command():
        db.init_db()
        print("Initialized the database.")

    @app.cli.command("seed")
    def seed_command():
        from .seed import run
        run()
        print("Seeded sample data.")

    @app.cli.command("prune-uploads")
    @click.option("--dry-run", is_flag=True, help="List orphans without deleting.")
    def prune_uploads_command(dry_run):
        """Delete uploaded photos no item points at any more."""
        from .photos import prune_uploads
        orphans = prune_uploads(dry_run=dry_run)
        for name in orphans:
            print(f"  {name}")
        print(f"{'Would remove' if dry_run else 'Removed'} "
              f"{len(orphans)} orphaned upload(s).")

    return app
