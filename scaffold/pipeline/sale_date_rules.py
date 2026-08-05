"""
Sale-date rule registry (v5.1.2-beta+).

Translators call derive_expected_sale_date(year, month, sale_date_rule)
to compute an expected_sale_date for foreclosure / sheriff sale leads.
The rule is selected by `sale_date_rule.rule_name` in the county config's
`geography.sale_date_rule` block.

This module is COUNTY-AGNOSTIC. State-specific rules are registered
as named entries; counties pick the named rule in config. Adding a
new state's rule means adding a new entry here, NOT modifying any
translator or pipeline code.

Built-in rules:
  - first_tuesday_of_month
        Used by states whose statute mandates the first Tuesday of
        the month (e.g. Texas, Georgia). Falls back to next Wednesday
        when the Tuesday is a state-recognized holiday (e.g. Jan 1,
        Jul 4) — configurable via sale_date_rule.holiday_shift.
  - first_monday_of_month
  - first_business_day_of_month
  - first_of_month  (the fallback when no rule is configured)
"""

from __future__ import annotations
import calendar
from datetime import date, timedelta


def _first_weekday_of_month(year: int, month: int, weekday: int) -> date:
    """Return the date of the first occurrence of `weekday` (0=Mon..6=Sun) in (year, month)."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset)


def _is_business_day(d: date) -> bool:
    return d.weekday() < 5  # Mon-Fri


def _apply_holiday_shift(d: date, holiday_shift: dict | None) -> date:
    """
    Apply optional holiday_shift rule. holiday_shift looks like:
        {"shift_dates": ["01-01", "07-04"], "shift_to": "next_wednesday"}
    """
    if not holiday_shift:
        return d
    shift_dates = holiday_shift.get("shift_dates", []) or []
    shift_to = holiday_shift.get("shift_to", "next_business_day")
    mmdd = f"{d.month:02d}-{d.day:02d}"
    if mmdd not in shift_dates:
        return d
    if shift_to == "next_wednesday":
        # Find the next Wednesday strictly after d.
        for _ in range(7):
            d += timedelta(days=1)
            if d.weekday() == 2:
                return d
    elif shift_to == "next_tuesday":
        for _ in range(7):
            d += timedelta(days=1)
            if d.weekday() == 1:
                return d
    elif shift_to == "next_weekday":
        d += timedelta(days=1)
        while d.weekday() >= 5:
            d += timedelta(days=1)
        return d
    elif shift_to == "next_business_day":
        d += timedelta(days=1)
        while not _is_business_day(d):
            d += timedelta(days=1)
        return d
    elif shift_to == "previous_business_day":
        d -= timedelta(days=1)
        while not _is_business_day(d):
            d -= timedelta(days=1)
        return d
    return d


# ---- Built-in rule implementations ----

def _rule_first_tuesday_of_month(year: int, month: int, sale_date_rule: dict) -> date:
    d = _first_weekday_of_month(year, month, 1)  # 1 = Tuesday
    return _apply_holiday_shift(d, sale_date_rule.get("holiday_shift"))


def _rule_first_monday_of_month(year: int, month: int, sale_date_rule: dict) -> date:
    d = _first_weekday_of_month(year, month, 0)  # 0 = Monday
    return _apply_holiday_shift(d, sale_date_rule.get("holiday_shift"))


def _rule_first_business_day_of_month(year: int, month: int, sale_date_rule: dict) -> date:
    d = date(year, month, 1)
    while not _is_business_day(d):
        d += timedelta(days=1)
    return _apply_holiday_shift(d, sale_date_rule.get("holiday_shift"))


def _rule_first_of_month(year: int, month: int, sale_date_rule: dict) -> date:
    return date(year, month, 1)


_RULES = {
    "first_tuesday_of_month": _rule_first_tuesday_of_month,
    "first_monday_of_month": _rule_first_monday_of_month,
    "first_business_day_of_month": _rule_first_business_day_of_month,
    "first_of_month": _rule_first_of_month,
}


def derive_expected_sale_date(
    year: int,
    month: int,
    sale_date_rule: dict | None,
) -> str:
    """
    Derive an expected sale date for the given (year, month) per the rule.

    Args:
        year: Recording / notice year.
        month: Recording / notice month.
        sale_date_rule: Dict from county config geography.sale_date_rule.
                        If empty or missing rule_name, falls back to
                        first-of-month.

    Returns:
        ISO 8601 date string (YYYY-MM-DD).
    """
    rule_name = (sale_date_rule or {}).get("rule_name", "first_of_month")
    impl = _RULES.get(rule_name, _RULES["first_of_month"])
    d = impl(year, month, sale_date_rule or {})
    return d.isoformat()


def registered_rules() -> list[str]:
    return sorted(_RULES.keys())


def register_rule(name: str, impl):
    """Allow county adapters to register custom rules (rare)."""
    _RULES[name] = impl
