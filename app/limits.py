"""Request-scoped anti-abuse plumbing: rate limits, client identity, audit log.

`hardening.py` holds the pure logic; this module is the thin Flask-aware layer
that binds it to a request. Split this way so the interesting parts stay
testable without a request context — the same shape as availability.py.
"""
import os
import sys

from flask import current_app, request

from . import hardening
from .hardening import NotificationBudget, RateLimiter

# (limit, window_seconds). Each gunicorn worker keeps its own counters, so the
# real-world allowance is roughly `--workers` times these numbers; they are set
# with that in mind. The August 18 attack was 21 bookings in 20 seconds.
RATE_LIMITS = {
    # key                  limit  window
    "reserve_burst":       (3,    120),     # 3 requests / 2 min per IP
    "reserve_sustained":   (10,   3600),    # 10 / hour per IP
    "reserve_item":        (2,    3600),    # 2 / hour against ONE item
    "login_failed":        (5,    900),     # 5 bad passwords / 15 min
    # Admin endpoints: stricter than public because the admin is authenticated.
    "admin_write":         (30,   3600),    # 30 write actions / hour per admin
}

# Outbound mail per recipient address per day. A booking generates up to three
# notifications across its lifecycle, so 12 leaves room for several legitimate
# bookings from one person while capping what an abuser can make us send.
MAIL_PER_ADDRESS_PER_DAY = int(os.environ.get("MAIL_PER_ADDRESS_PER_DAY", "12"))

limiter = RateLimiter()
mail_budget = NotificationBudget(limit=MAIL_PER_ADDRESS_PER_DAY)


def reset_for_tests():
    """Drop all counters. The limiter is process-global; tests need a clean one."""
    global limiter, mail_budget
    limiter = RateLimiter()
    mail_budget = NotificationBudget(limit=MAIL_PER_ADDRESS_PER_DAY)


def client_ip():
    """Best available client address, honouring ProxyFix when configured."""
    return request.remote_addr or "unknown"


def audit(event, **fields):
    """One structured JSON line per interesting outcome, on stdout.

    Same format as FreeStuff's, so one set of log queries works across the
    family. Never logs a renter's name, contact, email or notes — an address
    appears only as a truncated hash, which is enough to correlate a repeat
    offender without the log becoming a second copy of the booking table.
    """
    try:
        fields.setdefault("ip", client_ip())
        fields.setdefault("ua", (request.headers.get("User-Agent") or "")[:200])
        fields.setdefault("path", request.path)
    except RuntimeError:  # outside a request context (CLI, background task)
        pass
    hardening.log_event(sys.stdout, event, app="rentstuff", **fields)


def rate_limited(bucket, suffix=""):
    """Check one of the RATE_LIMITS buckets for this client.

    Returns (allowed, retry_after_seconds).
    """
    limit, window = RATE_LIMITS[bucket]
    key = f"{bucket}:{client_ip()}"
    if suffix:
        key = f"{key}:{suffix}"
    return limiter.check(key, limit, window)


def form_stamp():
    """Signed issue-time for the reserve form, for the template to embed."""
    return hardening.sign_form_stamp(current_app.config["SECRET_KEY"])


def admin_rate_limited():
    """Check the admin_write bucket for the current admin session.

    Returns (allowed, retry_after_seconds).  Keyed on the admin's session id
    rather than IP so a shared proxy doesn't throttle all admins at once.
    """
    from flask import session
    limit, window = RATE_LIMITS["admin_write"]
    key = f"admin_write:{session.get('session_id', client_ip())}"
    return limiter.check(key, limit, window)


def disposable_domains():
    """The blocklist, or None when the feature is switched off."""
    if current_app.config.get("BLOCK_DISPOSABLE_EMAIL"):
        return hardening.DISPOSABLE_DOMAINS
    return None
