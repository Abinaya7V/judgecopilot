"""
Validates a proposed shift swap against labor-hour constraints before
it's ever routed to a manager for approval. This is the core piece of
domain logic ShiftSwap adds on top of "just let people trade shifts."
"""
from datetime import timedelta
from dataclasses import dataclass


@dataclass
class ConstraintViolation:
    rule: str
    detail: str


DEFAULT_MIN_REST_HOURS = 8


def check_weekly_hour_cap(worker_shifts: list, new_shift, weekly_cap: int) -> ConstraintViolation | None:
    """Sum hours for the week containing new_shift; flag if it would
    push the worker over their configured weekly cap."""
    week_start = new_shift.start_time - timedelta(days=new_shift.start_time.weekday())
    week_end = week_start + timedelta(days=7)

    total_hours = sum(
        (s.end_time - s.start_time).total_seconds() / 3600
        for s in worker_shifts
        if week_start <= s.start_time < week_end
    )
    new_hours = (new_shift.end_time - new_shift.start_time).total_seconds() / 3600

    if total_hours + new_hours > weekly_cap:
        return ConstraintViolation(
            rule="weekly_hour_cap",
            detail=f"Would result in {total_hours + new_hours:.1f}h this week (cap: {weekly_cap}h)",
        )
    return None


def check_minimum_rest(worker_shifts: list, new_shift, min_rest_hours: int = DEFAULT_MIN_REST_HOURS) -> ConstraintViolation | None:
    """Flag if the new shift doesn't leave enough rest before/after an
    adjacent existing shift for the same worker."""
    for existing in worker_shifts:
        if existing.end_time <= new_shift.start_time:
            gap = (new_shift.start_time - existing.end_time).total_seconds() / 3600
        elif new_shift.end_time <= existing.start_time:
            gap = (existing.start_time - new_shift.end_time).total_seconds() / 3600
        else:
            return ConstraintViolation(
                rule="overlapping_shift",
                detail="New shift overlaps an existing scheduled shift",
            )

        if gap < min_rest_hours:
            return ConstraintViolation(
                rule="minimum_rest",
                detail=f"Only {gap:.1f}h rest before/after adjacent shift (min: {min_rest_hours}h)",
            )
    return None


def validate_swap(worker_shifts: list, new_shift, weekly_cap: int) -> list[ConstraintViolation]:
    violations = []
    cap_violation = check_weekly_hour_cap(worker_shifts, new_shift, weekly_cap)
    if cap_violation:
        violations.append(cap_violation)
    rest_violation = check_minimum_rest(worker_shifts, new_shift)
    if rest_violation:
        violations.append(rest_violation)
    return violations
