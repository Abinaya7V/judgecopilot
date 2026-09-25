"""Unit tests for the constraint engine — the core domain logic."""
from datetime import datetime, timedelta
from dataclasses import dataclass
from constraint_engine import check_weekly_hour_cap, check_minimum_rest, validate_swap


@dataclass
class FakeShift:
    start_time: datetime
    end_time: datetime


def test_weekly_cap_not_exceeded():
    monday = datetime(2026, 9, 21, 9, 0)
    existing = [FakeShift(monday, monday + timedelta(hours=8))]
    new_shift = FakeShift(monday + timedelta(days=1, hours=9), monday + timedelta(days=1, hours=17))
    result = check_weekly_hour_cap(existing, new_shift, weekly_cap=40)
    assert result is None


def test_weekly_cap_exceeded():
    monday = datetime(2026, 9, 21, 9, 0)
    existing = [
        FakeShift(monday + timedelta(days=i), monday + timedelta(days=i, hours=9))
        for i in range(4)
    ]
    new_shift = FakeShift(monday + timedelta(days=4, hours=9), monday + timedelta(days=4, hours=17))
    result = check_weekly_hour_cap(existing, new_shift, weekly_cap=40)
    assert result is not None
    assert result.rule == "weekly_hour_cap"


def test_minimum_rest_violation():
    day1_end = datetime(2026, 9, 21, 22, 0)
    existing = [FakeShift(day1_end - timedelta(hours=8), day1_end)]
    new_shift = FakeShift(day1_end + timedelta(hours=3), day1_end + timedelta(hours=11))
    result = check_minimum_rest(existing, new_shift, min_rest_hours=8)
    assert result is not None
    assert result.rule == "minimum_rest"


def test_overlapping_shift_detected():
    start = datetime(2026, 9, 21, 9, 0)
    existing = [FakeShift(start, start + timedelta(hours=8))]
    overlapping = FakeShift(start + timedelta(hours=4), start + timedelta(hours=12))
    result = check_minimum_rest(existing, overlapping)
    assert result is not None
    assert result.rule == "overlapping_shift"


def test_validate_swap_returns_multiple_violations():
    monday = datetime(2026, 9, 21, 9, 0)
    existing = [
        FakeShift(monday + timedelta(days=i), monday + timedelta(days=i, hours=9))
        for i in range(5)
    ]
    new_shift = FakeShift(monday + timedelta(days=4, hours=10), monday + timedelta(days=4, hours=18))
    violations = validate_swap(existing, new_shift, weekly_cap=40)
    assert len(violations) >= 1
