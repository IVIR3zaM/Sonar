"""Balance entry management for current balance tracking.

A balance can come from a bank export (source='import') or be set manually
(source='manual'). The latest by date is active, and on the same date a manual
entry is an explicit override.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True)
class BalanceEntry:
    """A recorded balance as of a date from a particular source."""

    as_of: date
    amount_cents: int
    source: str  # 'import' or 'manual'


def latest_balance(entries: list[BalanceEntry]) -> BalanceEntry | None:
    """Return the latest balance entry.

    Latest by date wins. On the same date, manual beats import because a manual
    entry is an explicit override of the household balance.
    """
    if not entries:
        return None

    # A manual entry is an explicit override of the import: it represents the
    # household's best knowledge of the current balance. max() with (as_of, source)
    # returns the latest date; on the same date, "manual" > "import" lexicographically.
    return max(entries, key=lambda e: (e.as_of, e.source))
