"""The core logic — the part that actually matters. No DB, no Flask."""
from datetime import date

import pytest

from app.availability import (Interval, find_conflicts, intervals_overlap,
                              nights_between, outstanding_by_renter, quote_amount)

d = date


def test_nights_between():
    assert nights_between(d(2026, 8, 10), d(2026, 8, 12)) == 2


def test_nights_between_rejects_bad_range():
    with pytest.raises(ValueError):
        nights_between(d(2026, 8, 12), d(2026, 8, 12))


def test_quote_day():
    assert quote_amount(45, "day", d(2026, 8, 10), d(2026, 8, 13)) == 135.0


def test_quote_week_rounds_up_partial_weeks():
    # 8 nights -> 2 weeks
    assert quote_amount(100, "week", d(2026, 8, 1), d(2026, 8, 9)) == 200.0


def test_quote_flat_ignores_duration():
    assert quote_amount(60, "flat", d(2026, 8, 1), d(2026, 8, 30)) == 60.0


def test_quote_unknown_unit():
    with pytest.raises(ValueError):
        quote_amount(10, "fortnight", d(2026, 8, 1), d(2026, 8, 2))


def test_overlap_partial():
    assert intervals_overlap(d(2026, 8, 1), d(2026, 8, 5),
                             d(2026, 8, 4), d(2026, 8, 8)) is True


def test_overlap_contained():
    assert intervals_overlap(d(2026, 8, 1), d(2026, 8, 10),
                             d(2026, 8, 3), d(2026, 8, 4)) is True


def test_adjacent_ranges_do_not_overlap():
    # one returns on the 5th, the next goes out on the 5th -> fine
    assert intervals_overlap(d(2026, 8, 1), d(2026, 8, 5),
                             d(2026, 8, 5), d(2026, 8, 9)) is False


def test_find_conflicts_filters_to_overlaps():
    blocking = [
        Interval(d(2026, 8, 1), d(2026, 8, 3)),   # before, no overlap
        Interval(d(2026, 8, 10), d(2026, 8, 14)),  # overlaps
        Interval(d(2026, 8, 20), d(2026, 8, 25)),  # after, no overlap
    ]
    hits = find_conflicts(d(2026, 8, 12), d(2026, 8, 16), blocking)
    assert len(hits) == 1
    assert hits[0].start == d(2026, 8, 10)


def test_find_conflicts_empty_when_free():
    blocking = [Interval(d(2026, 8, 1), d(2026, 8, 3))]
    assert find_conflicts(d(2026, 8, 10), d(2026, 8, 12), blocking) == []


def test_outstanding_skips_paid_and_cancelled():
    bookings = [
        {"renter_name": "Sam", "quoted_amount": 100, "is_paid": False, "status": "confirmed"},
        {"renter_name": "Sam", "quoted_amount": 50, "is_paid": True, "status": "returned"},
        {"renter_name": "Sam", "quoted_amount": 999, "is_paid": False, "status": "cancelled"},
        {"renter_name": "Ada", "quoted_amount": 25, "is_paid": False, "status": "confirmed"},
    ]
    assert outstanding_by_renter(bookings) == {"Sam": 100.0, "Ada": 25.0}
