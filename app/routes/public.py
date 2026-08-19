from datetime import date

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, send_from_directory, url_for)

from .. import hardening, mail, models
from ..availability import find_conflicts, quote_amount, to_date
from ..db import get_db
from ..limits import audit, disposable_domains, rate_limited
from ..models import DEFAULT_AGREEMENT

bp = Blueprint("public", __name__)

GENERIC_REJECTION = (
    "We couldn't accept that just now. Please reload the page and try again."
)

# An unbounded date range is a cheap denial-of-service — one POST can take an
# item off the calendar for years. Two months covers any real lend.
MAX_RENTAL_DAYS = 60


def _screen_request(item):
    """Bot checks and rate limits, before we look at the form's contents.

    Returns a response to send if the request should be refused, or None to
    carry on. Split out of item_detail because that view was already long, and
    because "did this come from a person" is a separate question from "is what
    they typed valid".
    """
    def refuse(reason, message, **extra):
        """Deliberately vague to the visitor, specific in the log.

        Naming the control that caught a bot ("you filled the honeypot") is free
        tuning feedback for whoever is probing the form. Genuine validation
        errors, further down, do get specific messages — those are real people
        making real mistakes.
        """
        audit("booking_rejected", reason=reason, item_id=item["id"], **extra)
        flash(message)
        return redirect(url_for("public.item_detail", slug=item["slug"]))

    if hardening.honeypot_tripped(request.form):
        return refuse("honeypot", GENERIC_REJECTION)

    ok, reason = hardening.check_form_stamp(
        current_app.config["SECRET_KEY"], request.form.get("form_stamp", ""))
    if not ok:
        if reason == "stamp_expired":
            # A real person who left the tab open. Say so plainly.
            return refuse(reason,
                          "This page went stale. Please reload and try again.")
        return refuse(reason, GENERIC_REJECTION)

    for bucket, suffix in (("reserve_burst", ""),
                           ("reserve_sustained", ""),
                           ("reserve_item", str(item["id"]))):
        allowed, retry_after = rate_limited(bucket, suffix)
        if not allowed:
            audit("rate_limited", bucket=bucket, item_id=item["id"],
                  retry_after=retry_after)
            flash("That's a lot of requests in a short time. "
                  "Please wait a few minutes and try again.")
            response = redirect(url_for("public.item_detail", slug=item["slug"]))
            response.headers["Retry-After"] = str(retry_after)
            return response

    return None


def _is_duplicate_request(item_id, contact, email, start, end):
    """True if this person already has a live request for the same window.

    The August 18 attack was 21 near-identical bookings. Even without spam, a
    double submit (impatient click, browser retry) otherwise creates two
    pending requests the owner has to reconcile by hand.
    """
    fingerprints = {hardening.contact_fingerprint(contact),
                    hardening.contact_fingerprint(email)} - {""}
    if not fingerprints or start is None:
        return False
    for row in models.open_bookings_for_item(item_id):
        existing = {hardening.contact_fingerprint(row["renter_contact"]),
                    hardening.contact_fingerprint(row["renter_email"])} - {""}
        if fingerprints & existing and to_date(row["start_date"]) == start \
                and to_date(row["end_date"]) == end:
            return True
    return False


@bp.route("/")
def index():
    items = models.list_items(active_only=True)
    today = date.today()
    statuses = {i["id"]: models.current_status(i["id"], today) for i in items}
    return render_template("index.html", items=items, statuses=statuses)


@bp.route("/item/<slug>", methods=("GET", "POST"))
def item_detail(slug):
    item = models.get_item_by_slug(slug)
    if item is None or not item["is_active"]:
        abort(404)

    if request.method == "POST":
        rejection = _screen_request(item)
        if rejection is not None:
            return rejection

        renter_name = hardening.clean_text(
            request.form.get("renter_name"), hardening.NAME_MAX)
        renter_contact = hardening.clean_text(
            request.form.get("renter_contact"), hardening.CONTACT_MAX)
        renter_email = hardening.clean_text(
            request.form.get("renter_email"), hardening.EMAIL_MAX)
        notes = hardening.clean_text(
            request.form.get("notes"), hardening.NOTE_MAX, collapse_whitespace=False)

        errors, reasons = [], []

        def fail(reason, message):
            reasons.append(reason)
            errors.append(message)

        # Unlike FreeStuff's single "how do we reach you" box, RentStuff has two
        # fields and the phone/handle one is marked optional — so the rule is
        # "at least one usable way to reach you", not "this specific field".
        # Validate whichever were filled in, then insist on having got one.
        checks = [hardening.check_name(renter_name), hardening.check_note(notes),
                  hardening.check_email(renter_email,
                                        disposable_domains=disposable_domains())]
        if renter_contact:
            checks.append(hardening.check_contact(renter_contact,
                                                  disposable_domains()))
        for ok, reason, message in checks:
            if not ok:
                fail(reason, message)

        if not renter_email and not renter_contact:
            fail("no_contact_method",
                 "Please add an email address or a phone number so we can reach you.")

        if not request.form.get("agree"):
            fail("terms_not_accepted",
                 "Please accept the rental terms to continue.")
        try:
            start = to_date(request.form["start_date"])
            end = to_date(request.form["end_date"])
            if end <= start:
                fail("dates_reversed", "Return date must be after the pickup date.")
            elif start < date.today():
                # The form carries a min= attribute, but that's a client-side
                # hint only — a direct POST could book a window in the past,
                # which no availability check would ever flag as conflicting.
                fail("date_past", "Pickup date can't be in the past.")
            elif (end - start).days > MAX_RENTAL_DAYS:
                # An open-ended range is a cheap denial-of-service: one request
                # can mark an item unavailable for years.
                fail("range_too_long",
                     f"Rentals are limited to {MAX_RENTAL_DAYS} days. "
                     "Get in touch for anything longer.")
        except (KeyError, ValueError):
            fail("date_invalid", "Please give a valid pickup and return date.")
            start = end = None

        if not errors:
            blocking = models.blocking_intervals_for_item(item["id"])
            if find_conflicts(start, end, blocking):
                fail("date_conflict", "Those dates aren't free — pick another range.")

        if not errors and _is_duplicate_request(item["id"], renter_contact,
                                                renter_email, start, end):
            audit("booking_duplicate", item_id=item["id"])
            flash("You've already requested this one for those dates — "
                  "we'll be in touch shortly.")
            return redirect(url_for("public.item_detail", slug=slug))

        if errors:
            audit("booking_rejected", item_id=item["id"], reason=",".join(reasons))
            for e in errors:
                flash(e)
        else:
            quote = quote_amount(item["rate_amount"], item["rate_unit"], start, end)
            booking_id = models.create_booking(
                item_id=item["id"], renter_name=renter_name,
                renter_contact=renter_contact, renter_email=renter_email,
                start_date=start, end_date=end, quoted_amount=quote,
                deposit_amount=item["deposit_amount"], notes=notes,
                status="requested", agreed_terms=1,
            )
            audit("booking_accepted", item_id=item["id"], booking_id=booking_id)
            mail.notify_new_request(booking_id)
            flash("Request sent — you'll get a confirmation once it's approved.")
            return redirect(url_for("public.item_detail", slug=slug))

    agreement_text = models.get_setting("agreement_text", DEFAULT_AGREEMENT)
    return render_template("item_detail.html", item=item,
                           agreement_text=agreement_text,
                           today=date.today().isoformat())


@bp.route("/media/<path:filename>")
def media(filename):
    """Serve an uploaded item photo from the upload directory."""
    return send_from_directory(current_app.config["UPLOAD_DIR"], filename)


@bp.route("/healthz")
def healthz():
    """Liveness probe for Docker and the reverse proxy.

    Deliberately touches the database: a process that's up but can't reach its
    SQLite file (volume didn't remount, permissions changed) is the failure
    worth catching, and a bare 200 wouldn't catch it.
    """
    try:
        # Deliberately queries a real table. "SELECT 1" is answered without
        # touching the file at all, and sqlite3.connect() *creates* a missing
        # database — so the naive probe reports healthy against a vanished
        # volume or a corrupt file, which is precisely what it's here to catch.
        get_db().execute("SELECT 1 FROM item LIMIT 1").fetchone()
    except Exception:
        current_app.logger.exception("healthz: database probe failed")
        return {"status": "error"}, 503
    return {"status": "ok"}, 200
