import functools
from urllib.parse import urlparse

from flask import (Blueprint, current_app, flash, redirect, render_template,
                   request, session, url_for)
from werkzeug.security import check_password_hash

from . import limits
from .limits import RATE_LIMITS, audit, client_ip

bp = Blueprint("auth", __name__)


def login_required(view):
    @functools.wraps(view)
    def wrapped(**kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("auth.login", next=request.path))
        return view(**kwargs)
    return wrapped


def safe_next(target):
    """Return `target` only if it's a path on this site, else the dashboard.

    The previous version redirected to `next` unfiltered, so
    `/login?next=https://evil.example` sent an admin straight off-site with our
    login page as the referrer — a ready-made phishing hop. Rejecting anything
    with a scheme or a host is the whole fix; note that a protocol-relative
    "//evil.example" parses with netloc set, so it's caught too.
    """
    if not target:
        return url_for("admin.dashboard")
    parsed = urlparse(target)
    if parsed.scheme or parsed.netloc or not target.startswith("/"):
        return url_for("admin.dashboard")
    return target


@bp.route("/login", methods=("GET", "POST"))
def login():
    if request.method == "POST":
        # Checked before the password comparison, which also caps how much CPU
        # a brute-forcer can make us spend on hashing. Only failures count, so
        # an admin signing in from several devices never locks themselves out.
        limit, window = RATE_LIMITS["login_failed"]
        key = f"login_failed:{client_ip()}"
        # Reached through the module, not bound at import: the limiter object
        # is replaced wholesale on reset, and an early binding would keep
        # pointing at the old one.
        allowed, retry_after = limits.limiter.peek(key, limit, window)
        if not allowed:
            audit("login_throttled", retry_after=retry_after)
            flash(f"Too many failed sign-in attempts. Try again in "
                  f"{max(1, retry_after // 60)} minute(s).")
            return render_template("login.html"), 429, {
                "Retry-After": str(retry_after)}

        username = request.form.get("username", "")
        password = request.form.get("password", "")
        ok = (
            username == current_app.config["ADMIN_USERNAME"]
            and check_password_hash(current_app.config["ADMIN_PASSWORD_HASH"], password)
        )
        if ok:
            limits.limiter.reset(key)
            audit("login_ok")
            session.clear()
            session["is_admin"] = True
            return redirect(safe_next(request.args.get("next")))
        limits.limiter.check(key, limit, window)
        audit("login_failed")
        flash("Wrong username or password.")
    return render_template("login.html")


@bp.route("/logout", methods=("POST",))
def logout():
    """POST only.

    As a GET this was drive-by triggerable: an <img src="/logout"> on any page
    an admin visited would sign them out. Harmless on its own, but it's a state
    change from a cross-site request, which is exactly what CSRF protection is
    for — and Flask-WTF only guards non-GET methods.
    """
    session.clear()
    return redirect(url_for("public.index"))
