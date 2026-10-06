"""Detect recurring payments in categorized transactions (SPEC §6 Detection).

`detect_recurring` finds outgoing payments; `detect_income` finds recurring
credits in income categories, minus the salary (SPEC §13 Recurring income).
Both share one grouping and detection path. Pure functions only: rows and
`today` are passed in, the store decides what to keep. Each detected payment
gets a stable key so later runs update it instead of creating a duplicate; a
key that holds several payments on one day splits into `<key>#<rank>` series.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from statistics import median_low

from sonar.categorization.groups import EXCLUDED_FROM_RECURRENCE, INCOME
from sonar.importing.dedup import normalize_text
from sonar.recurring import schedule
from sonar.recurring.schedule import TOLERANCE, SchedulePeriod, add_months
from sonar.transactions import ParsedTransaction

# Shorter intervals need more evidence: two payments a month apart are often chance.
MIN_PAYMENTS = {1: 3, 2: 3, 3: 3, 6: 2, 12: 2}
EXCLUDED_TYPES = EXCLUDED_FROM_RECURRENCE
NAME_LENGTH = 40
# Days from the salary day within which an income series is the salary itself.
SALARY_DAY_DISTANCE = 7
DAYS_IN_MONTH_CYCLE = 31

Row = tuple[ParsedTransaction, str | None]


@dataclass(frozen=True)
class DetectedPayment:
    key: str
    name: str
    category: str | None
    schedule: SchedulePeriod
    last_paid_date: date
    next_due_date: date | None


def detect_recurring(
    rows: Iterable[Row], category_types: dict[str, str], today: date
) -> list[DetectedPayment]:
    def is_outgoing(tx: ParsedTransaction, category: str | None) -> bool:
        return tx.amount_cents < 0 and category_types.get(category or "") not in EXCLUDED_TYPES

    return _detect_series(rows, is_outgoing, today)


def detect_income(
    rows: Iterable[Row], category_types: dict[str, str], salary_day: int, today: date
) -> list[DetectedPayment]:
    def is_income_credit(tx: ParsedTransaction, category: str | None) -> bool:
        return tx.amount_cents > 0 and category_types.get(category or "") == INCOME

    series = _detect_series(rows, is_income_credit, today)
    return [p for p in series if not _is_salary(p.schedule.day, salary_day)]


def _is_salary(typical_day: int, salary_day: int) -> bool:
    # Days wrap at the month end: day 2 is close to day 28 of the month before.
    gap = abs(typical_day - salary_day)
    return min(gap, DAYS_IN_MONTH_CYCLE - gap) <= SALARY_DAY_DISTANCE


def _detect_series(
    rows: Iterable[Row], keep: Callable[[ParsedTransaction, str | None], bool], today: date
) -> list[DetectedPayment]:
    rows = list(rows)
    if not rows:
        return []
    latest_booking = max(tx.booking_date for tx, _ in rows)
    kept = [(tx, category) for tx, category in rows if keep(tx, category)]
    keys = (key for _, key in series_keys(tx for tx, _ in kept))
    groups: dict[str, list[Row]] = defaultdict(list)
    for row, key in zip(kept, keys, strict=True):
        groups[key].append(row)
    detected = (_detect_group(key, group, latest_booking, today) for key, group in groups.items())
    return sorted((p for p in detected if p is not None), key=lambda p: p.key)


def payment_key(tx: ParsedTransaction) -> str:
    # Mandate refs are only unique per creditor, so the creditor is part of the key.
    if tx.mandate_ref:
        return f"mandate:{tx.creditor_id or ''}/{tx.mandate_ref}"
    if tx.creditor_id:
        return f"creditor:{tx.creditor_id}"
    return f"counterparty:{normalize_text(tx.counterparty)}"


def series_keys(txs: Iterable[ParsedTransaction]) -> list[tuple[ParsedTransaction, str]]:
    # One mandate can carry several charges on one day; each charge is its own
    # series, ranked on its date by amount so a skipped small charge keeps the rest in place.
    txs = list(txs)
    base_keys = [payment_key(tx) for tx in txs]
    by_group_date: dict[tuple[str, date], list[int]] = defaultdict(list)
    for index, (tx, base) in enumerate(zip(txs, base_keys, strict=True)):
        by_group_date[(base, tx.booking_date)].append(index)
    splitting = {base for (base, _), indexes in by_group_date.items() if len(indexes) > 1}

    ranks = [1] * len(txs)
    for indexes in by_group_date.values():
        largest_first = sorted(indexes, key=lambda i: (-abs(txs[i].amount_cents), i))
        for rank, index in enumerate(largest_first, start=1):
            ranks[index] = rank
    return [
        (tx, f"{base}#{rank}" if base in splitting else base)
        for tx, base, rank in zip(txs, base_keys, ranks, strict=True)
    ]


def _detect_group(
    key: str, group: list[Row], latest_booking: date, today: date
) -> DetectedPayment | None:
    group = sorted(group, key=lambda row: row[0].booking_date)
    dates = [tx.booking_date for tx, _ in group]
    for interval, min_payments in MIN_PAYMENTS.items():
        run = _trailing_run(dates, interval)
        if len(run) >= min_payments:
            break
    else:
        return None

    last_paid = run[-1]
    if add_months(last_paid, interval, last_paid.day) + TOLERANCE < latest_booking:
        return None  # the series has stopped; forecasting it would invent payments

    latest_tx, latest_category = group[-1]
    day = median_low(d.day for d in run)
    period = SchedulePeriod(
        starts_on=_nearest_due_date(run[0], day),
        until=None,
        amount_cents=abs(latest_tx.amount_cents),
        interval_months=interval,
        day=day,
    )
    return DetectedPayment(
        key=key,
        name=latest_tx.counterparty.strip() or latest_tx.purpose.strip()[:NAME_LENGTH],
        category=latest_category,
        schedule=period,
        last_paid_date=last_paid,
        next_due_date=schedule.next_due_date((period,), last_paid, today),
    )


def _trailing_run(dates: list[date], interval: int) -> list[date]:
    """The longest run ending at the latest payment where each gap fits `interval`."""
    run = [dates[-1]]
    for earlier in reversed(dates[:-1]):
        expected = add_months(earlier, interval, earlier.day)
        if abs(run[0] - expected) > TOLERANCE:
            break
        run.insert(0, earlier)
    return run


def _nearest_due_date(first_paid: date, day: int) -> date:
    # A schedule anchors on the first `day` on or after starts_on; starting on a
    # late first payment would push a 2+ month schedule one month out of phase.
    candidates = (add_months(first_paid, months, day) for months in (-1, 0, 1))
    return min(candidates, key=lambda due: abs(due - first_paid))
