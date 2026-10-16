"""Utilities model: meters, readings, exchanges and billing periods (SPEC §13 Utilities).

Pure dataclasses and validation. Readings are integer thousandths of the meter
unit, prices and factors are scaled integers, money is integer cents.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

KINDS = frozenset({"gas", "electricity", "water"})
ADVANCE_MODES = frozenset({"flexible", "schedule"})
SCHEDULE_GRACE_DAYS = 14  # an advance may fall this long after the settlement date
MAX_DEBIT_DAYS = 365


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
class Charge:
    """A water charge (drinking or wastewater): price per m³ and base fee per year, net; VAT."""

    unit_price_micro: int  # millionths of a euro per m³
    base_fee_cents: int  # per year, net
    vat_percent: int


@dataclass(frozen=True)
class BillingPeriod:
    start_date: date
    settlement_date: date  # inclusive last day
    base_fee_cents: int | None  # per month; gas and electricity only
    unit_price_micro: int | None  # millionths of a euro per kWh; gas and electricity only
    state_factor_e4: int | None  # gas only
    calorific_value_e4: int | None  # gas only, kWh per m³
    advance_cents: int  # per month
    expected_usage: int  # per year
    category: str | None
    settled_cents: int | None = None  # signed as on the bill; None = not settled
    drinking: Charge | None = None  # water only
    wastewater: Charge | None = None  # water only
    advance_mode: str = "flexible"
    advance_dates: tuple[date, ...] = ()  # the due dates of a "schedule" period
    settlement_debit_days: int = 0  # days after the settlement date the bank debits it


def check_period(period: BillingPeriod, kind: str) -> None:
    if period.settlement_date < period.start_date:
        raise FieldError("settlement_date", "settlement date must not be before the start date")
    _check_prices(period, kind)
    for name in ("advance_cents", "expected_usage"):
        if getattr(period, name) < 0:
            raise FieldError(name, f"{name} must not be negative")
    for name in ("state_factor_e4", "calorific_value_e4"):
        value = getattr(period, name)
        if kind == "gas" and (value is None or value <= 0):
            raise FieldError(name, f"{name} is required for gas and must be positive")
        if kind != "gas" and value is not None:
            raise FieldError(name, f"{name} must be empty for {kind}")
    _check_advances(period)
    if not 0 <= period.settlement_debit_days <= MAX_DEBIT_DAYS:
        raise FieldError("settlement_debit_days", f"debit days must be 0 to {MAX_DEBIT_DAYS}")


def _check_prices(period: BillingPeriod, kind: str) -> None:
    if kind == "water":
        for name in ("unit_price_micro", "base_fee_cents"):
            if getattr(period, name) is not None:
                raise FieldError(name, f"{name} must be empty for water")
        _check_charge("drinking", period.drinking)
        _check_charge("wastewater", period.wastewater)
        return
    if period.unit_price_micro is None or period.unit_price_micro <= 0:
        raise FieldError("unit_price_micro", "unit price must be positive")
    if period.base_fee_cents is None or period.base_fee_cents < 0:
        raise FieldError("base_fee_cents", "base_fee_cents must not be negative")
    for name in ("drinking", "wastewater"):
        if getattr(period, name) is not None:
            raise FieldError(name, f"{name} must be empty for {kind}")


def _check_charge(name: str, charge: Charge | None) -> None:
    if charge is None:
        raise FieldError(name, f"{name} charge is required for water")
    if charge.unit_price_micro <= 0:
        raise FieldError(f"{name}_price_micro", f"{name} price must be positive")
    if charge.base_fee_cents < 0:
        raise FieldError(f"{name}_base_fee_cents", f"{name} base fee must not be negative")
    if not 0 <= charge.vat_percent <= 100:
        raise FieldError(f"{name}_vat_percent", f"{name} VAT must be 0 to 100 percent")


def _check_advances(period: BillingPeriod) -> None:
    dates = period.advance_dates
    if period.advance_mode not in ADVANCE_MODES:
        raise FieldError("advance_mode", f"advance mode must be one of {sorted(ADVANCE_MODES)}")
    if period.advance_mode == "flexible":
        if dates:
            raise FieldError("advance_dates", "a flexible period has no advance dates")
        return
    if not dates:
        raise FieldError("advance_dates", "a schedule needs at least one advance date")
    if len(set(dates)) != len(dates):
        raise FieldError("advance_dates", "advance dates must be unique")
    last = period.settlement_date + timedelta(days=SCHEDULE_GRACE_DAYS)
    if any(not period.start_date <= day <= last for day in dates):
        raise FieldError(
            "advance_dates",
            f"advance dates must fall between {period.start_date.isoformat()} "
            f"and {last.isoformat()}",
        )


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
