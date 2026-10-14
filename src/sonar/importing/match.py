"""Pair incoming bookings with stored ones, so a booking that arrives both in a CSV
export and from the bank sync is stored once (SPEC §13 Bank sync).

The two sources describe one booking with the same account, date, amount and
counterparty, but the sync may cut the purpose short. Rows with an equal key pair
first on purpose (one text starts the other), then one-to-one in order.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date
from typing import Protocol

from sonar.importing.dedup import normalize_text


class Booking(Protocol):
    @property
    def account(self) -> str: ...
    @property
    def booking_date(self) -> date: ...
    @property
    def amount_cents(self) -> int: ...
    @property
    def counterparty(self) -> str: ...
    @property
    def purpose(self) -> str: ...


def pair(incoming: Sequence[Booking], stored: Sequence[Booking]) -> dict[int, int]:
    """Map the index of each matched incoming row to the index of its stored row."""
    stored_by_key = _indexes_by_key(stored)
    pairs: dict[int, int] = {}
    for key, incoming_indexes in _indexes_by_key(incoming).items():
        pairs.update(
            _pair_within_key(incoming_indexes, stored_by_key.get(key, []), incoming, stored)
        )
    return pairs


def _pair_within_key(
    incoming_indexes: list[int],
    free: list[int],
    incoming: Sequence[Booking],
    stored: Sequence[Booking],
) -> dict[int, int]:
    free = list(free)
    pairs: dict[int, int] = {}
    leftover = []
    for i in incoming_indexes:
        purpose = normalize_text(incoming[i].purpose)
        match = next(
            (s for s in free if _one_starts_the_other(purpose, normalize_text(stored[s].purpose))),
            None,
        )
        if match is None:
            leftover.append(i)
        else:
            pairs[i] = match
            free.remove(match)
    # Same key but unrelated texts: still the same bookings, so pair them by count.
    pairs.update(zip(leftover, free, strict=False))
    return pairs


def _indexes_by_key(rows: Sequence[Booking]) -> dict[tuple, list[int]]:
    groups: dict[tuple, list[int]] = defaultdict(list)
    for index, row in enumerate(rows):
        key = (row.account, row.booking_date, row.amount_cents, normalize_text(row.counterparty))
        groups[key].append(index)
    return groups


def _one_starts_the_other(a: str, b: str) -> bool:
    shorter, longer = sorted((a, b), key=len)
    return longer.startswith(shorter)
