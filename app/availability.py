"""Pure scheduling + billing helpers.

No Flask, no database — everything in here is a plain function over primitives
so the core logic (overlap detection, quoting, the outstanding rollup) can be
unit-tested without spinning up an app or a DB. This is the part worth testing
hard; the rest of the app is a thin layer on top of it.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from math import ceil

# Statuses that hard-block a date range for an item. 'requested' is intentionally
# NOT here: pending requests are surfaced as soft warnings, not conflicts.
BLOCKING_STATUSES = ("confirmed",)


def to_date(value) -> date:
    """Coerce a date, a datetime, or a 'YYYY-MM-DD...' string to a date.

    Dates reach us from three directions — form fields (strings), SQLite rows
    (strings or dates, depending on the adapter) and code (real dates) — so
    every layer needs the same coercion. It lives here so there is exactly one.

    Raises ValueError on anything unparseable, which callers turn into a
    user-facing message rather than a 500.
    """
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


@dataclass(frozen=True)
class Interval:
    """A half-open date range [start, end): the end date is the return day,
    on which the item is free again."""
    start: date
    end: date


def nights_between(start: date, end: date) -> int:
    """Number of rental nights. Pick up on the 10th, return on the 12th -> 2."""
    if end <= start:
        raise ValueError("end date must be after start date")
    return (end - start).days


def quote_amount(rate_amount: float, rate_unit: str, start: date, end: date) -> float:
    """Compute a quote. 'day' = rate * nights, 'week' = rate * whole-or-part
    weeks, 'flat' = rate regardless of duration. Always overridable upstream."""
    nights = nights_between(start, end)
    if rate_unit == "day":
        return round(rate_amount * nights, 2)
    if rate_unit == "week":
        return round(rate_amount * ceil(nights / 7), 2)
    if rate_unit == "flat":
        return round(float(rate_amount), 2)
    raise ValueError(f"unknown rate_unit: {rate_unit!r}")


def intervals_overlap(a_start: date, a_end: date, b_start: date, b_end: date) -> bool:
    """Half-open overlap test. Two ranges touching end-to-start (one returns the
    same day the next goes out) do NOT count as overlapping."""
    return a_start < b_end and b_start < a_end


def find_conflicts(new_start: date, new_end: date, blocking_intervals) -> list[Interval]:
    """Return every blocking Interval that overlaps [new_start, new_end)."""
    if new_end <= new_start:
        raise ValueError("end date must be after start date")
    return [
        iv for iv in blocking_intervals
        if intervals_overlap(new_start, new_end, iv.start, iv.end)
    ]


def _field(row, name):
    """Read a field from a mapping, a sqlite3.Row, or a plain object.

    The isinstance(row, dict) test this used to do was wrong for the app's real
    input: sqlite3.Row is subscriptable but is NOT a dict and has no attributes,
    so every live call fell through to getattr() and raised. Try subscripting
    first and fall back to attributes, which covers all three shapes.
    """
    try:
        return row[name]
    except (TypeError, KeyError, IndexError):
        return getattr(row, name)


def outstanding_by_renter(bookings) -> dict[str, float]:
    """Sum unpaid, non-cancelled quoted amounts, grouped by renter name."""
    totals: dict[str, float] = defaultdict(float)
    for b in bookings:
        if _field(b, "status") == "cancelled":
            continue
        if not _field(b, "is_paid"):
            totals[_field(b, "renter_name")] += float(_field(b, "quoted_amount"))
    return {k: round(v, 2) for k, v in totals.items()}
