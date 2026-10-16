"""Utilities model: meters, readings, exchanges and billing periods (SPEC §13 Utilities).

Pure dataclasses and validation. Readings are integer thousandths of the meter
unit, prices and factors are scaled integers, money is integer cents.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

KINDS = frozenset({"gas", "electricity"})


class FieldError(ValueError):
    """A rejected input; `field` names the form or API field to blame."""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class Meter:
    name: str
    kind: str

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise FieldError("name", "name must not be blank")
        if self.kind not in KINDS:
            raise FieldError("kind", f"kind must be one of {sorted(KINDS)}, got {self.kind!r}")


@dataclass(frozen=True)
class Reading:
    reading_date: date
    value_milli: int


@dataclass(frozen=True)
class Exchange:
    """A meter swap: the old meter ends at `old_final_milli`, the new at `new_start_milli`."""

    exchange_date: date
    old_final_milli: int
    new_start_milli: int


@dataclass(frozen=True)
class BillingPeriod:
    start_date: date
    settlement_date: date  # inclusive last day
    base_fee_cents: int  # per month
    unit_price_micro: int  # millionths of a euro per kWh
    state_factor_e4: int | None  # gas only
    calorific_value_e4: int | None  # gas only, kWh per m³
    advance_cents: int  # per month
    expected_usage: int  # per year
    category: str | None
    settled_cents: int | None = None  # signed as on the bill; None = not settled


def check_period(period: BillingPeriod, kind: str) -> None:
    if period.settlement_date < period.start_date:
        raise FieldError("settlement_date", "settlement date must not be before the start date")
    if period.unit_price_micro <= 0:
        raise FieldError("unit_price_micro", "unit price must be positive")
    for name in ("base_fee_cents", "advance_cents", "expected_usage"):
        if getattr(period, name) < 0:
            raise FieldError(name, f"{name} must not be negative")
    for name in ("state_factor_e4", "calorific_value_e4"):
        value = getattr(period, name)
        if kind == "gas" and (value is None or value <= 0):
            raise FieldError(name, f"{name} is required for gas and must be positive")
        if kind != "gas" and value is not None:
            raise FieldError(name, f"{name} must be empty for {kind}")


def check_periods(periods: Iterable[BillingPeriod], kind: str) -> None:
    """Each period is valid and a meter's periods never overlap."""
    ordered = sorted(periods, key=lambda period: period.start_date)
    for period in ordered:
        check_period(period, kind)
    for earlier, later in zip(ordered, ordered[1:], strict=False):
        if later.start_date <= earlier.settlement_date:
            raise FieldError(
                "start_date",
                f"period starting {later.start_date.isoformat()} overlaps the one ending "
                f"{earlier.settlement_date.isoformat()}",
            )
