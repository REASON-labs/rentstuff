import re
from datetime import date, datetime

from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, url_for)

from .. import models
from ..auth import login_required
from ..availability import outstanding_by_renter

bp = Blueprint("admin", __name__)


def _slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "item"


@bp.route("/")
@login_required
def dashboard():
    all_bookings = models.list_bookings()
    outstanding = outstanding_by_renter(all_bookings)
    today = date.today()

    active, returns_due, requested = [], [], []
    for b in all_bookings:
        start = str(b["start_date"])[:10]
        end = str(b["end_date"])[:10]
        if b["status"] == "requested":
            requested.append(b)
        elif b["status"] == "confirmed":
            active.append(b)
            if end <= str(today):
                returns_due.append(b)

    return render_template(
        "admin/dashboard.html",
        outstanding=outstanding,
        total_outstanding=round(sum(outstanding.values()), 2),
        active=active, returns_due=returns_due, requested=requested,
    )


@bp.route("/items")
@login_required
def items():
    return render_template("admin/items.html", items=models.list_items())


@bp.route("/items/new", methods=("GET", "POST"))
@login_required
def item_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        if not name:
            flash("Name is required.")
            return render_template("admin/item_form.html", form=request.form)
        models.create_item(
            name=name,
            slug=_slugify(request.form.get("slug") or name),
            description=request.form.get("description", "").strip(),
            rate_amount=float(request.form.get("rate_amount") or 0),
            rate_unit=request.form.get("rate_unit", "day"),
            deposit_amount=float(request.form.get("deposit_amount") or 0),
        )
        flash("Item added.")
        return redirect(url_for("admin.items"))
    return render_template("admin/item_form.html", form={})


@bp.route("/items/<int:item_id>/toggle", methods=("POST",))
@login_required
def item_toggle(item_id):
    item = models.get_item(item_id)
    if item is None:
        abort(404)
    models.set_item_active(item_id, not item["is_active"])
    return redirect(url_for("admin.items"))


@bp.route("/bookings")
@login_required
def bookings():
    return render_template("admin/bookings.html", bookings=models.list_bookings())


@bp.route("/bookings/<int:booking_id>/status", methods=("POST",))
@login_required
def booking_status(booking_id):
    new_status = request.form.get("status", "")
    if new_status not in ("requested", "confirmed", "returned", "cancelled"):
        abort(400)
    models.set_booking_status(booking_id, new_status)
    flash(f"Booking marked {new_status}.")
    return redirect(url_for("admin.bookings"))


@bp.route("/bookings/<int:booking_id>/paid", methods=("POST",))
@login_required
def booking_paid(booking_id):
    b = models.get_booking(booking_id)
    if b is None:
        abort(404)
    amount = float(request.form.get("paid_amount") or b["quoted_amount"])
    method = request.form.get("payment_method", "cash")
    reference = request.form.get("payment_ref") or None  # e.g. Zoho invoice #
    models.mark_booking_paid(booking_id, amount, method, reference)
    flash("Marked paid.")
    return redirect(url_for("admin.bookings"))
