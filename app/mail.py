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
"""
import base64
import os
import urllib.parse
import urllib.request

from flask import current_app

from . import models


def send_email(to, subject, text):
    """Send one email. Returns True on success, False if unsent. Never raises."""
    if not to:
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
        send_email(b["renter_email"], f"Confirmed — {c['item']}",
                   f"Hi {c['renter']},\n\nYou're confirmed for {c['item']}, "
                   f"{c['start']} to {c['end']}. Total ${c['amount']}"
                   f"{f' plus a ${c['deposit']} deposit' if b['deposit_amount'] else ''}. "
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
