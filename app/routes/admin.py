import functools
import math
import re
from datetime import date

from flask import (Blueprint, abort, flash, redirect, render_template,
                   request, url_for)

from .. import limits, mail, models
from ..db import get_db as _get_db
from ..auth import login_required
from ..availability import (find_conflicts, outstanding_by_renter,
                            quote_amount, to_date)
from ..availability import BOOKING_TRANSITIONS
from ..models import DEFAULT_AGREEMENT
from ..photos import DEFAULT_IMAGES, discard_upload, save_upload


def admin_write_required(view):
    """Rate-limit admin write actions alongside login_required."""
    @functools.wraps(view)
    def wrapped(**kwargs):
        if request.method != "POST":
            return view(**kwargs)
        allowed, retry_after = limits.admin_rate_limited()
        if not allowed:
            flash(f"Too many actions in a short time. Try again in "
                  f"{max(1, retry_after // 60)} minute(s).")
            return redirect(url_for("admin.dashboard")), 429, {
                "Retry-After": str(retry_after)}
        return view(**kwargs)
    return wrapped

bp = Blueprint("admin", __name__)

BOOL_SETTINGS = ("notify_on_request", "notify_on_confirm", "notify_on_paid")
BOOKING_STATUSES = ("requested", "confirmed", "returned", "cancelled")
RATE_UNITS = ("day", "week", "flat")


def _slugify(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "item"


def _unique_slug(base):
    """Derive a URL slug from the name, adding -2, -3 ... if it's taken."""
    slug, n = base, 2
    while models.get_item_by_slug(slug) is not None:
        slug, n = f"{base}-{n}", n + 1
    return slug


def _money(field, default=0.0):
    """Parse a currency form field. Blank means the default; a stray '$' or
    thousands comma is tolerated. Returns None for anything that isn't a
    non-negative number, so callers can flash a message instead of 500-ing."""
    raw = (request.form.get(field) or "").strip()
    if not raw:
        return default
    try:
        value = float(raw.replace(",", "").lstrip("$").strip())
    except ValueError:
        return None
    # float() happily parses 'nan' and 'inf'. NaN fails no comparison, so a
    # bare `value < 0` lets it through, and it then hits a REAL NOT NULL column
    # as SQL NULL -> IntegrityError -> the exact 500 this function exists to
    # stop. inf is worse: it stores fine and poisons every quote and rollup it
    # touches, permanently. Require a finite number.
    if not math.isfinite(value) or value < 0:
        return None
    return round(value, 2)


def _item_form_values():
    """Pull and validate the item fields shared by create and edit.
    Returns (values, errors); values is only safe to use when errors is empty."""
    errors = []

    name = request.form.get("name", "").strip()
    if not name:
        errors.append("Name is required.")

    rate = _money("rate_amount")
    if rate is None:
        errors.append("Rate must be a number, and can't be negative.")

    deposit = _money("deposit_amount")
    if deposit is None:
        errors.append("Deposit must be a number, and can't be negative.")

    unit = request.form.get("rate_unit", "day")
    if unit not in RATE_UNITS:
        errors.append("Rate unit must be day, week or flat.")

    return {
        "name": name,
        "description": request.form.get("description", "").strip(),
        "rate_amount": rate,
        "rate_unit": unit,
        "deposit_amount": deposit,
    }, errors


def _resolve_photo(existing):
    """Uploaded photo wins; else a chosen default; else 'remove'; else keep."""
    up = save_upload(request.files.get("photo"))
    if up:
        return up
    choice = request.form.get("default_image", "")
    if choice in DEFAULT_IMAGES:
        return choice
    if request.form.get("remove_photo"):
        return None
    return existing


# ---- dashboard -------------------------------------------------------------

@bp.route("/")
@login_required
def dashboard():
    all_bookings, _ = models.list_bookings()
    outstanding = outstanding_by_renter(all_bookings)
    today = str(date.today())

    active, returns_due, requested = [], [], []
    for b in all_bookings:
        if b["status"] == "requested":
            requested.append(b)
        elif b["status"] == "confirmed":
            active.append(b)
            if str(b["end_date"])[:10] <= today:
                returns_due.append(b)

    return render_template(
        "admin/dashboard.html",
        outstanding=outstanding,
        total_outstanding=round(sum(outstanding.values()), 2),
        active=active, returns_due=returns_due, requested=requested,
    )


# ---- items -----------------------------------------------------------------

@bp.route("/items")
@login_required
def items():
    return render_template("admin/items.html",
                           items=models.list_items(),
                           booking_counts=models.booking_counts_by_item())


@bp.route("/items/new", methods=("GET", "POST"))
@login_required
@admin_write_required
def item_new():
    if request.method == "POST":
        values, errors = _item_form_values()
        if errors:
            for e in errors:
                flash(e)
            return render_template("admin/item_form.html", form=request.form,
                                   defaults=DEFAULT_IMAGES, editing=False, item=None)
        models.create_item(
            slug=_unique_slug(_slugify(values["name"])),
            photo_path=_resolve_photo(None),
            **values,
        )
        flash("Item added.")
        return redirect(url_for("admin.items"))
    return render_template("admin/item_form.html", form={}, defaults=DEFAULT_IMAGES,
                           editing=False, item=None)


@bp.route("/items/<int:item_id>/edit", methods=("GET", "POST"))
@login_required
@admin_write_required
def item_edit(item_id):
    item = models.get_item(item_id)
    if item is None:
        abort(404)
    if request.method == "POST":
        values, errors = _item_form_values()   # slug intentionally left unchanged
        if errors:
            for e in errors:
                flash(e)
            return render_template("admin/item_form.html", form=request.form,
                                   defaults=DEFAULT_IMAGES, editing=True, item=item)
        old_photo = item["photo_path"]
        new_photo = _resolve_photo(old_photo)
        models.update_item(item_id, photo_path=new_photo, **values)
        if new_photo != old_photo:
            discard_upload(old_photo)   # after the write: never orphan a live row
        flash("Item updated.")
        return redirect(url_for("admin.items"))
    return render_template("admin/item_form.html", form=dict(item), defaults=DEFAULT_IMAGES,
                           editing=True, item=item)


@bp.route("/items/<int:item_id>/toggle", methods=("POST",))
@login_required
@admin_write_required
def item_toggle(item_id):
    item = models.get_item(item_id)
    if item is None:
        abort(404)
    models.set_item_active(item_id, not item["is_active"])
    return redirect(url_for("admin.items"))


@bp.route("/items/<int:item_id>/delete", methods=("POST",))
@login_required
@admin_write_required
def item_delete(item_id):
    """Delete an item outright — only allowed while it has no rental history.
    Once bookings reference it, deleting would erase that history, so we steer
    the admin to hiding it instead."""
    item = models.get_item(item_id)
    if item is None:
        abort(404)
    photo = item["photo_path"]
    if not models.delete_item_if_unbooked(item_id):
        # The guard lives in the SQL; the count here is only for the message.
        n = models.count_bookings_for_item(item_id)
        flash(f"Can't delete “{item['name']}” — it has {n} booking"
              f"{'s' if n != 1 else ''} on record. Hide it instead.")
        return redirect(url_for("admin.items"))
    discard_upload(photo)
    flash(f"Deleted “{item['name']}”.")
    return redirect(url_for("admin.items"))


# ---- blackouts -------------------------------------------------------------

@bp.route("/items/<int:item_id>/blackouts", methods=("GET", "POST"))
@login_required
@admin_write_required
def item_blackouts(item_id):
    item = models.get_item(item_id)
    if item is None:
        abort(404)
    if request.method == "POST":
        try:
            start, end = to_date(request.form["start_date"]), to_date(request.form["end_date"])
            if end <= start:
                flash("End date must be after the start date.")
            else:
                models.create_blackout(item_id, start, end,
                                       request.form.get("reason", "").strip())
                flash("Blackout added.")
        except (KeyError, ValueError):
            flash("Please give valid start and end dates.")
        return redirect(url_for("admin.item_blackouts", item_id=item_id))
    return render_template("admin/blackouts.html", item=item,
                           blackouts=models.list_blackouts(item_id))


@bp.route("/blackouts/<int:blackout_id>/delete", methods=("POST",))
@login_required
@admin_write_required
def blackout_delete(blackout_id):
    item_id = request.form.get("item_id")
    if not item_id:
        flash("Item ID is required.")
        return redirect(url_for("admin.dashboard"))
    # Verify the blackout belongs to the specified item before deleting.
    row = _get_db().execute(
        "SELECT item_id FROM blackout WHERE id = ?", (blackout_id,)
    ).fetchone()
    if row is None:
        flash("Blackout not found.")
        return redirect(url_for("admin.dashboard"))
    if row["item_id"] != int(item_id):
        flash("That blackout does not belong to the specified item.")
        return redirect(url_for("admin.dashboard"))
    models.delete_blackout(blackout_id)
    flash("Blackout removed.")
    return redirect(url_for("admin.item_blackouts", item_id=item_id))


# ---- bookings --------------------------------------------------------------

@bp.route("/bookings")
@login_required
def bookings():
    page = max(1, int(request.args.get("page", 1)))
    per_page = 20
    rows, total = models.list_bookings(status=request.args.get("status", "") or None,
                                       page=page, per_page=per_page)
    total_pages = max(1, (total + per_page - 1) // per_page)
    return render_template("admin/bookings.html",
                           rows=rows,
                           bookings=rows,
                           current_status=request.args.get("status", "") or None,
                           page=page,
                           total_pages=total_pages,
                           per_page=per_page,
                           BOOKING_TRANSITIONS=BOOKING_TRANSITIONS)


@bp.route("/bookings/new", methods=("GET", "POST"))
@login_required
@admin_write_required
def booking_new():
    items_list = models.list_items()
    if request.method == "POST":
        errors = []
        try:
            item_id = int(request.form["item_id"])
        except (KeyError, ValueError):
            item_id, errors = None, errors + ["Pick an item."]
        item = models.get_item(item_id) if item_id else None
        if item is None:
            errors.append("Pick an item.")
        renter_name = request.form.get("renter_name", "").strip()
        if not renter_name:
            errors.append("Renter name is required.")
        try:
            start = to_date(request.form["start_date"])
            end = to_date(request.form["end_date"])
            if end <= start:
                errors.append("Return date must be after the pickup date.")
        except (KeyError, ValueError):
            start = end = None
            errors.append("Please give valid pickup and return dates.")

        status = request.form.get("status", "confirmed")
        if not errors and status == "confirmed":
            blocking = models.blocking_intervals_for_item(item["id"])
            if find_conflicts(start, end, blocking):
                errors.append("Those dates clash with a confirmed booking or blackout.")

        if errors:
            for e in errors:
                flash(e)
            return render_template("admin/booking_form.html", items=items_list,
                                   form=request.form)

        override = _money("quoted_amount", default=None)
        if override is None and request.form.get("quoted_amount", "").strip():
            flash("Quoted amount must be a number, and can't be negative.")
            return render_template("admin/booking_form.html", items=items_list,
                                   form=request.form)
        quote = (override if override is not None
                 else quote_amount(item["rate_amount"], item["rate_unit"], start, end))
        models.create_booking(
            item_id=item["id"], renter_name=renter_name,
            renter_contact=request.form.get("renter_contact", "").strip(),
            renter_email=request.form.get("renter_email", "").strip(),
            start_date=start, end_date=end, quoted_amount=quote,
            deposit_amount=item["deposit_amount"],
            notes=request.form.get("notes", "").strip(), status=status,
        )
        flash("Booking added.")
        return redirect(url_for("admin.bookings"))
    return render_template("admin/booking_form.html", items=items_list, form={})


@bp.route("/bookings/<int:booking_id>/status", methods=("POST",))
@login_required
@admin_write_required
def booking_status(booking_id):
    new_status = request.form.get("status", "")
    if new_status not in BOOKING_STATUSES:
        abort(400)
    b = models.get_booking(booking_id)
    if b is None:
        abort(404)
    if new_status == "confirmed":
        blocking = models.blocking_intervals_for_item(b["item_id"],
                                                      exclude_booking_id=booking_id)
        if find_conflicts(to_date(b["start_date"]), to_date(b["end_date"]), blocking):
            flash("Can't confirm — those dates clash with another confirmed "
                  "booking or a blackout.")
            return redirect(url_for("admin.bookings"))
    if not models.set_booking_status(booking_id, new_status):
        flash(f"Can't change booking status to '{new_status}' from '{b['status']}'.")
        return redirect(url_for("admin.bookings"))
    flash(f"Booking marked {new_status}.")
    if new_status == "confirmed":
        mail.notify_confirmed(booking_id)
    return redirect(url_for("admin.bookings"))


@bp.route("/bookings/<int:booking_id>/paid", methods=("POST",))
@login_required
@admin_write_required
def booking_paid(booking_id):
    b = models.get_booking(booking_id)
    if b is None:
        abort(404)
    amount = _money("paid_amount", default=b["quoted_amount"])
    if amount is None:
        flash("Paid amount must be a number, and can't be negative.")
        return redirect(url_for("admin.bookings"))
    method = request.form.get("payment_method", "cash")
    reference = request.form.get("payment_ref") or None
    models.mark_booking_paid(booking_id, amount, method, reference)
    flash("Marked paid.")
    mail.notify_paid(booking_id)
    return redirect(url_for("admin.bookings"))


# ---- settings --------------------------------------------------------------

@bp.route("/settings", methods=("GET", "POST"))
@login_required
@admin_write_required
def settings():
    if request.method == "POST":
        for k in BOOL_SETTINGS:
            models.set_setting(k, "1" if request.form.get(k) else "0")
        models.set_setting("admin_email", request.form.get("admin_email", "").strip())
        models.set_setting("agreement_text",
                           request.form.get("agreement_text", "").strip() or DEFAULT_AGREEMENT)
        flash("Settings saved.")
        return redirect(url_for("admin.settings"))
    return render_template(
        "admin/settings.html",
        toggles={k: models.get_setting(k, "1") == "1" for k in BOOL_SETTINGS},
        admin_email=models.get_setting("admin_email", ""),
        agreement_text=models.get_setting("agreement_text", DEFAULT_AGREEMENT),
    )
