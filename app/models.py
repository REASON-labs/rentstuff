"""Thin data-access layer over sqlite. Routes call these; the interesting
scheduling/billing math lives in availability.py."""
from __future__ import annotations

from datetime import date, datetime

from .availability import Interval, BLOCKING_STATUSES
from .db import get_db


# ---- items ---------------------------------------------------------------

def list_items(active_only: bool = False):
    q = "SELECT * FROM item"
    if active_only:
        q += " WHERE is_active = 1"
    q += " ORDER BY name COLLATE NOCASE"
    return get_db().execute(q).fetchall()


def get_item(item_id: int):
    return get_db().execute("SELECT * FROM item WHERE id = ?", (item_id,)).fetchone()


def get_item_by_slug(slug: str):
    return get_db().execute("SELECT * FROM item WHERE slug = ?", (slug,)).fetchone()


def create_item(name, slug, description, rate_amount, rate_unit,
                deposit_amount, photo_path=None, is_active=1):
    db = get_db()
    cur = db.execute(
        """INSERT INTO item (name, slug, description, photo_path, rate_amount,
                             rate_unit, deposit_amount, is_active)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (name, slug, description, photo_path, rate_amount, rate_unit,
         deposit_amount, is_active),
    )
    db.commit()
    return cur.lastrowid


def set_item_active(item_id: int, is_active: bool):
    db = get_db()
    db.execute("UPDATE item SET is_active = ? WHERE id = ?",
               (1 if is_active else 0, item_id))
    db.commit()


# ---- blocking intervals (bookings + blackouts) ---------------------------

def _to_date(value) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def blocking_intervals_for_item(item_id: int) -> list[Interval]:
    """Confirmed bookings + blackout windows — everything that hard-blocks
    a new request for this item."""
    db = get_db()
    placeholders = ",".join("?" for _ in BLOCKING_STATUSES)
    rows = db.execute(
        f"""SELECT start_date, end_date FROM booking
            WHERE item_id = ? AND status IN ({placeholders})""",
        (item_id, *BLOCKING_STATUSES),
    ).fetchall()
    blackouts = db.execute(
        "SELECT start_date, end_date FROM blackout WHERE item_id = ?",
        (item_id,),
    ).fetchall()
    return [
        Interval(_to_date(r["start_date"]), _to_date(r["end_date"]))
        for r in list(rows) + list(blackouts)
    ]


# ---- bookings ------------------------------------------------------------

def create_booking(item_id, renter_name, renter_contact, start_date, end_date,
                   quoted_amount, deposit_amount, notes="", status="requested"):
    db = get_db()
    cur = db.execute(
        """INSERT INTO booking (item_id, renter_name, renter_contact, start_date,
                                end_date, status, quoted_amount, deposit_amount, notes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (item_id, renter_name, renter_contact, start_date, end_date, status,
         quoted_amount, deposit_amount, notes),
    )
    db.commit()
    return cur.lastrowid


def list_bookings(status=None):
    db = get_db()
    if status:
        rows = db.execute(
            """SELECT b.*, i.name AS item_name FROM booking b
               JOIN item i ON i.id = b.item_id
               WHERE b.status = ? ORDER BY b.start_date""",
            (status,),
        ).fetchall()
    else:
        rows = db.execute(
            """SELECT b.*, i.name AS item_name FROM booking b
               JOIN item i ON i.id = b.item_id
               ORDER BY b.start_date DESC""",
        ).fetchall()
    return rows


def get_booking(booking_id: int):
    return get_db().execute(
        """SELECT b.*, i.name AS item_name FROM booking b
           JOIN item i ON i.id = b.item_id WHERE b.id = ?""",
        (booking_id,),
    ).fetchone()


def set_booking_status(booking_id: int, status: str):
    db = get_db()
    db.execute("UPDATE booking SET status = ? WHERE id = ?", (status, booking_id))
    db.commit()


def mark_booking_paid(booking_id: int, paid_amount, method, reference=None):
    db = get_db()
    db.execute(
        """UPDATE booking
           SET is_paid = 1, paid_amount = ?, payment_method = ?,
               payment_ref = ?, paid_at = datetime('now')
           WHERE id = ?""",
        (paid_amount, method, reference, booking_id),
    )
    db.commit()
