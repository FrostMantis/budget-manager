"""Input parsing helpers for form data.

Every route that reads a number from request.form goes through here, so that a
blank field or a stray minus sign produces a flash message and a redirect
instead of a 500.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import flash

# Matches Numeric(10, 2): eight digits before the point, two after.
MAX_AMOUNT = Decimal("99999999.99")
CENTS = Decimal("0.01")


class InputError(ValueError):
    """Raised when submitted form data cannot be used."""


def parse_amount(raw, field="Amount", allow_zero=False, allow_negative=False):
    """Parse a money value from form input into a Decimal.

    Returns Decimal, not float, because the money columns are Numeric(10, 2) —
    SQLAlchemy hands back Decimal on read, and Decimal - float is a TypeError.

    request.form.get('x', 0) only falls back to the default when the key is
    absent; an empty input posts '' and would blow up float(). Handle both.
    """
    if raw is None or str(raw).strip() == "":
        raise InputError(f"{field} is required.")
    try:
        value = Decimal(str(raw).strip())
    except (TypeError, ValueError, InvalidOperation):
        raise InputError(f"{field} must be a number.")
    if not value.is_finite():
        raise InputError(f"{field} must be a number.")
    value = value.quantize(CENTS, rounding=ROUND_HALF_UP)
    if not allow_negative and value < 0:
        raise InputError(f"{field} cannot be negative.")
    if not allow_zero and value == 0:
        raise InputError(f"{field} must be greater than zero.")
    if abs(value) > MAX_AMOUNT:
        raise InputError(f"{field} is too large.")
    return value


def parse_id(raw, field="Selection"):
    """Parse a row id from form input. int(None) raises TypeError, so guard."""
    if raw is None or str(raw).strip() == "":
        raise InputError(f"{field} is required.")
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise InputError(f"{field} is invalid.")


def parse_name(raw, field="Name", max_length=50):
    """Parse and bound a free-text name so it cannot overflow the column."""
    value = (raw or "").strip()
    if not value:
        raise InputError(f"{field} is required.")
    if len(value) > max_length:
        raise InputError(f"{field} must be {max_length} characters or fewer.")
    return value


def parse_choice(raw, allowed, field="Value"):
    """Parse a value that must come from a fixed set.

    Guards against a crafted POST creating, say, a second 'savings' bucket,
    which the service layer's filter_by(...).first() lookups assume never
    happens.
    """
    value = (raw or "").strip()
    if value not in allowed:
        raise InputError(f"{field} is invalid.")
    return value


def flash_error(err):
    """Surface an InputError to the user."""
    flash(str(err), "danger")
