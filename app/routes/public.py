import re
from datetime import date, datetime

from flask import (Blueprint, abort, current_app, flash, redirect,
                   render_template, request, send_from_directory, url_for)

from .. import mail, models
from ..availability import find_conflicts, quote_amount
from ..models import DEFAULT_AGREEMENT

bp = Blueprint("public", __name__)


def _parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


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
        renter_name = request.form.get("renter_name", "").strip()
        renter_contact = request.form.get("renter_contact", "").strip()
        renter_email = request.form.get("renter_email", "").strip()
        notes = request.form.get("notes", "").strip()
        errors = []
        if not renter_name:
            errors.append("Please add your name.")
        if not request.form.get("agree"):
            errors.append("Please accept the rental terms to continue.")
        try:
            start = _parse_date(request.form["start_date"])
            end = _parse_date(request.form["end_date"])
            if end <= start:
                errors.append("Return date must be after the pickup date.")
        except (KeyError, ValueError):
            errors.append("Please give a valid pickup and return date.")
            start = end = None

        if not errors:
            blocking = models.blocking_intervals_for_item(item["id"])
            if find_conflicts(start, end, blocking):
                errors.append("Those dates aren't free — pick another range.")

        if errors:
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
            mail.notify_new_request(booking_id)
            flash("Request sent — you'll get a confirmation once it's approved.")
            return redirect(url_for("public.item_detail", slug=slug))

    agreement_text = models.get_setting("agreement_text", DEFAULT_AGREEMENT)
    return render_template("item_detail.html", item=item, agreement_text=agreement_text)


@bp.route("/media/<path:filename>")
def media(filename):
    """Serve an uploaded item photo from the upload directory."""
    return send_from_directory(current_app.config["UPLOAD_DIR"], filename)
