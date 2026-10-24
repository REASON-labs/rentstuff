"""Email notifications.

Provider-agnostic: everything goes through send_email(to, subject, text). The
backend here is Mailgun (HTTP API), selected at runtime from env vars; to swap
providers (SMTP, SES, Postmark…) replace send_email's body — the notify_* layer
below is unaware of the provider. With no mail env set, send_email is a safe
no-op (logged), so the app runs fine before you configure anything.

Env:
  MAILGUN_API_KEY, MAILGUN_DOMAIN   enable sending
  MAIL_FROM                         optional From (defaults to postmaster@domain)
  ADMIN_EMAIL                       fallback admin recipient (Settings value wins)

Whether each event actually sends is gated by Settings toggles
(notify_on_request / notify_on_confirm / notify_on_paid), default on.

Security (hardening spec, Category 4): every recipient address is validated and
budget-checked inside send_email, so no notification path can be turned into a
relay for mailing strangers. See the docstring there.
"""
import base64
import os
import urllib.parse
import urllib.request

from flask import current_app

from . import hardening, limits, models
from .limits import audit


def send_email(to, subject, text):
    """Send one email. Returns True on success, False if unsent. Never raises.

    The two guards below live *here* rather than at the form, deliberately. The
    reserve form is not the only thing that can create a booking — the admin
    add-booking screen does too, and a future importer or API might. Putting the
    check at the single point where mail actually leaves means no call site can
    forget it.

    The threat is specific: RentStuff is a machine that sends email to an
    address a stranger typed into a public form. Left unguarded, anyone can put
    a victim's address in and have our domain, our reputation and our Mailgun
    account deliver to them — a reflection relay, and a quick route to a
    blocklisted sending domain.
    """
    if not to:
        return False

    ok, reason, _ = hardening.check_email(to, required=True)
    if not ok:
        audit("mail_rejected", reason=reason)
        current_app.logger.warning("refusing to send to a malformed address")
        return False

    if not limits.mail_budget.allow(to):
        # Per-address daily cap. The form's rate limiter stops a flood of
        # bookings; this stops a flood of *mail*, which isn't the same thing —
        # an attacker spreading submissions across IPs to dodge the form limiter
        # would otherwise still get us to mail their victim over and over.
        audit("mail_budget_exceeded",
              recipient_fp=hardening.contact_fingerprint(to)[:12])
        current_app.logger.warning("daily mail budget exhausted for a recipient")
        return False

    key = os.environ.get("MAILGUN_API_KEY")
    domain = os.environ.get("MAILGUN_DOMAIN")
    sender = os.environ.get("MAIL_FROM") or (f"RentStuff <postmaster@{domain}>" if domain else "")
    if not (key and domain and sender):
        current_app.logger.info("email not sent (mail unconfigured): to=%s subj=%s", to, subject)
        return False
    data = urllib.parse.urlencode(
        {"from": sender, "to": to, "subject": subject, "text": text}).encode()
    req = urllib.request.Request(f"https://api.mailgun.net/v3/{domain}/messages", data=data)
    req.add_header("Authorization", "Basic " + base64.b64encode(f"api:{key}".encode()).decode())
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return 200 <= resp.status < 300
    except Exception as e:  # email must never break the request flow
        current_app.logger.warning("email send failed: %s", e)
        return False


# ---- helpers ---------------------------------------------------------------

def _admin_email():
    return models.get_setting("admin_email", "") or os.environ.get("ADMIN_EMAIL", "")


def _ctx(booking, item):
    return {
        "item": item["name"],
        "renter": booking["renter_name"],
        "start": str(booking["start_date"])[:10],
        "end": str(booking["end_date"])[:10],
        "amount": f"{booking['quoted_amount']:.2f}",
        "deposit": f"{booking['deposit_amount']:.2f}",
        "paid": f"{booking['paid_amount']:.2f}",
        "method": booking["payment_method"] or "",
        "ref": booking["payment_ref"] or "",
    }


# ---- event notifications (each gated by its Settings toggle) ---------------
# NOTE: message wording lives here as defaults. A future Settings screen can
# override these templates; that editor is intentionally deferred for now.

def notify_new_request(booking_id):
    if models.get_setting("notify_on_request", "1") != "1":
        return
    b = models.get_booking(booking_id)
    if b is None:
        return
    c = _ctx(b, models.get_item(b["item_id"]))
    admin = _admin_email()
    if admin:
        send_email(admin, f"New rental request — {c['item']}",
                   f"{c['renter']} requested {c['item']} for {c['start']} to {c['end']} "
                   f"(quote ${c['amount']}). Review it in the admin.")
    if b["renter_email"]:
        send_email(b["renter_email"], f"We got your request — {c['item']}",
                   f"Hi {c['renter']},\n\nThanks — we received your request to rent "
                   f"{c['item']} from {c['start']} to {c['end']}. We'll confirm shortly.")


def notify_confirmed(booking_id):
    if models.get_setting("notify_on_confirm", "1") != "1":
        return
    b = models.get_booking(booking_id)
    if b is None:
        return
    c = _ctx(b, models.get_item(b["item_id"]))
    if b["renter_email"]:
        deposit_extra = (f" plus a ${c['deposit']} deposit" if b['deposit_amount'] else "")
        send_email(b["renter_email"], f"Confirmed — {c['item']}",
                   f"Hi {c['renter']},\n\nYou're confirmed for {c['item']}, "
                   f"{c['start']} to {c['end']}. Total ${c['amount']}"
                   f"{deposit_extra}. "
                   f"See you at pickup!")
    admin = _admin_email()
    if admin:
        send_email(admin, f"Confirmed — {c['item']} ({c['renter']})",
                   f"{c['item']} is confirmed for {c['renter']}, {c['start']} to {c['end']}.")


def notify_paid(booking_id):
    if models.get_setting("notify_on_paid", "1") != "1":
        return
    b = models.get_booking(booking_id)
    if b is None:
        return
    c = _ctx(b, models.get_item(b["item_id"]))
    ref = f" (ref {c['ref']})" if c["ref"] else ""
    body = (f"Payment received for {c['item']}, {c['start']} to {c['end']}.\n"
            f"Paid ${c['paid']} via {c['method']}{ref}. Thank you!")
    if b["renter_email"]:
        send_email(b["renter_email"], f"Receipt — {c['item']}", f"Hi {c['renter']},\n\n{body}")
    admin = _admin_email()
    if admin:
        send_email(admin, f"Paid — {c['item']} ({c['renter']})", body)
