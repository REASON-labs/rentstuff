"""Thin data-access layer over sqlite. Routes call these; the interesting
scheduling/billing math lives in availability.py."""
from __future__ import annotations

from .availability import BLOCKING_STATUSES, BOOKING_TRANSITIONS, Interval, to_date
from .db import get_db

DEFAULT_AGREEMENT = (
    "I agree to return this item on time and in the condition I received it, "
    "and I understand I'm responsible for any loss or damage while it's in my care."
)


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


def update_item(item_id, name, description, rate_amount, rate_unit,
                deposit_amount, photo_path):
    """Update an item. Slug is intentionally left unchanged (it's in the public
    URL). photo_path is written as given — the route decides keep/replace/clear."""
    db = get_db()
    db.execute(
        """UPDATE item SET name = ?, description = ?, rate_amount = ?,
                           rate_unit = ?, deposit_amount = ?, photo_path = ?
           WHERE id = ?""",
        (name, description, rate_amount, rate_unit, deposit_amount, photo_path, item_id),
    )
    db.commit()


def set_item_active(item_id: int, is_active: bool):
    db = get_db()
    db.execute("UPDATE item SET is_active = ? WHERE id = ?",
               (1 if is_active else 0, item_id))
    db.commit()


def count_bookings_for_item(item_id: int) -> int:
    """How many bookings reference this item, in any status. Deleting an item
    would orphan its rental history, so this is the guard on that."""
    row = get_db().execute(
        "SELECT COUNT(*) AS n FROM booking WHERE item_id = ?", (item_id,)
    ).fetchone()
    return row["n"]


def all_photo_paths() -> set[str]:
    """Every photo_path any item points at — the reference set the upload
    pruner diffs the upload directory against."""
    rows = get_db().execute(
        "SELECT photo_path FROM item WHERE photo_path IS NOT NULL AND photo_path != ''"
    ).fetchall()
    return {r["photo_path"] for r in rows}


def booking_counts_by_item() -> dict[int, int]:
    """{item_id: booking count} for every item that has any — one query, so the
    items list can show what's deletable without going N+1."""
    rows = get_db().execute(
        "SELECT item_id, COUNT(*) AS n FROM booking GROUP BY item_id"
    ).fetchall()
    return {r["item_id"]: r["n"] for r in rows}


def delete_item_if_unbooked(item_id: int) -> bool:
    """Delete an item and its blackouts, but only while it has no bookings.
    Returns True if it was deleted, False if bookings held it back.

    The guard is in the SQL rather than in the route on purpose. booking.item_id
    is ON DELETE CASCADE, so a check-then-delete pair has a window: a public
    request that commits between the two turns the delete into a silent cascade
    that destroys the very booking that should have prevented it. One
    conditional statement can't be raced that way.
    """
    db = get_db()
    cur = db.execute(
        """DELETE FROM item
           WHERE id = ?
             AND NOT EXISTS (SELECT 1 FROM booking WHERE item_id = ?)""",
        (item_id, item_id),
    )
    if cur.rowcount == 0:
        db.rollback()
        return False
    db.execute("DELETE FROM blackout WHERE item_id = ?", (item_id,))
    db.commit()
    return True


# ---- blocking intervals (bookings + blackouts) ---------------------------

def blocking_intervals_for_item(item_id: int,
                                exclude_booking_id: int | None = None) -> list[Interval]:
    """Everything that hard-blocks a date range for this item: bookings in a
    BLOCKING_STATUS plus blackout windows.

    exclude_booking_id ignores a single booking, which is what the confirm-time
    re-check needs so a pending booking doesn't collide with itself.
    """
    db = get_db()
    placeholders = ",".join("?" for _ in BLOCKING_STATUSES)
    sql = f"""SELECT start_date, end_date FROM booking
              WHERE item_id = ? AND status IN ({placeholders})"""
    params: list = [item_id, *BLOCKING_STATUSES]
    if exclude_booking_id is not None:
        sql += " AND id != ?"
        params.append(exclude_booking_id)

    rows = db.execute(sql, params).fetchall()
    blackouts = db.execute(
        "SELECT start_date, end_date FROM blackout WHERE item_id = ?",
        (item_id,),
    ).fetchall()
    return [
        Interval(to_date(r["start_date"]), to_date(r["end_date"]))
        for r in list(rows) + list(blackouts)
    ]


def open_bookings_for_item(item_id: int):
    """Bookings still live enough to count as a duplicate if repeated.

    'requested' and 'confirmed' only: a cancelled request should never stop the
    same person asking again, and a returned one is history. Kept here rather
    than in the route so the status list lives next to BLOCKING_STATUSES, which
    it deliberately differs from — 'requested' doesn't block a date, but it does
    make a second identical request a duplicate.
    """
    return get_db().execute(
        "SELECT renter_contact, renter_email, start_date, end_date "
        "FROM booking WHERE item_id = ? AND status IN ('requested', 'confirmed')",
        (item_id,),
    ).fetchall()


# ---- bookings ------------------------------------------------------------

def create_booking(item_id, renter_name, renter_contact, start_date, end_date,
                   quoted_amount, deposit_amount, notes="", status="requested",
                   renter_email="", agreed_terms=0):
    db = get_db()
    cur = db.execute(
        """INSERT INTO booking (item_id, renter_name, renter_contact, renter_email,
                                start_date, end_date, status, quoted_amount,
                                deposit_amount, notes, agreed_terms)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (item_id, renter_name, renter_contact, renter_email, start_date, end_date,
         status, quoted_amount, deposit_amount, notes, int(bool(agreed_terms))),
    )
    db.commit()
    return cur.lastrowid


def list_bookings(status=None, page: int = 1, per_page: int = 20):
    """List bookings with optional status filter and pagination.

    Returns (rows, total_count) where total_count is the total number of
    matching rows (without pagination) so the caller can compute page count.
    """
    db = get_db()
    if status:
        count_sql = """SELECT COUNT(*) AS n FROM booking b
                       JOIN item i ON i.id = b.item_id
                       WHERE b.status = ?"""
        list_sql = """SELECT b.*, i.name AS item_name FROM booking b
                      JOIN item i ON i.id = b.item_id
                      WHERE b.status = ? ORDER BY b.start_date DESC
                      LIMIT ? OFFSET ?"""
        params: list = [status, per_page, (page - 1) * per_page]
    else:
        count_sql = """SELECT COUNT(*) AS n FROM booking b
                       JOIN item i ON i.id = b.item_id"""
        list_sql = """SELECT b.*, i.name AS item_name FROM booking b
                      JOIN item i ON i.id = b.item_id
                      ORDER BY b.start_date DESC
                      LIMIT ? OFFSET ?"""
        params = [per_page, (page - 1) * per_page]
    total = db.execute(count_sql, (status,) if status else ()).fetchone()["n"]
    rows = db.execute(list_sql, params).fetchall()
    return rows, total


def get_booking(booking_id: int):
    return get_db().execute(
        """SELECT b.*, i.name AS item_name FROM booking b
           JOIN item i ON i.id = b.item_id WHERE b.id = ?""",
        (booking_id,),
    ).fetchone()


def set_booking_status(booking_id: int, status: str) -> bool:
    """Set a booking's status, enforcing the state machine.

    Returns True if the transition was applied, False if it was rejected
    because the current status cannot reach *status* (an invalid transition).
    """
    db = get_db()
    row = db.execute(
        "SELECT status FROM booking WHERE id = ?", (booking_id,)
    ).fetchone()
    if row is None:
        return False
    current = row["status"]
    allowed = BOOKING_TRANSITIONS.get(current, frozenset())
    if status not in allowed:
        return False
    db.execute("UPDATE booking SET status = ? WHERE id = ?", (status, booking_id))
    db.commit()
    return True


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


# ---- catalog status ------------------------------------------------------

def current_status(item_id: int, today):
    """Is this item out right now? Half-open [start, end): out when
    start_date <= today < end_date on a confirmed booking."""
    row = get_db().execute(
        """SELECT end_date FROM booking
           WHERE item_id = ? AND status = 'confirmed'
             AND start_date <= ? AND end_date > ?
           ORDER BY end_date DESC LIMIT 1""",
        (item_id, today, today),
    ).fetchone()
    if row:
        return {"state": "out", "until": str(row["end_date"])[:10]}
    return {"state": "available", "until": None}


# ---- blackouts -------------------------------------------------------------

def list_blackouts(item_id):
    return get_db().execute(
        "SELECT * FROM blackout WHERE item_id = ? ORDER BY start_date", (item_id,)
    ).fetchall()


def create_blackout(item_id, start_date, end_date, reason=""):
    db = get_db()
    db.execute(
        "INSERT INTO blackout (item_id, start_date, end_date, reason) VALUES (?, ?, ?, ?)",
        (item_id, start_date, end_date, reason),
    )
    db.commit()


def delete_blackout(blackout_id):
    db = get_db()
    db.execute("DELETE FROM blackout WHERE id = ?", (blackout_id,))
    db.commit()


# ---- settings (key/value) --------------------------------------------------

def get_setting(key, default=""):
    row = get_db().execute("SELECT value FROM setting WHERE key = ?", (key,)).fetchone()
    return row["value"] if row is not None else default


def set_setting(key, value):
    db = get_db()
    db.execute(
        """INSERT INTO setting (key, value) VALUES (?, ?)
           ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
        (key, str(value)),
    )
    db.commit()
