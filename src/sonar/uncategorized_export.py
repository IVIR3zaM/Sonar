"""Build the copy-to-Claude-Code export for uncategorized transactions (SPEC §5).

The "Uncategorized" page turns unmatched rows into one compact text block.
Pasting it into Claude Code triggers the CLAUDE.md Categorization workflow,
which reads and writes categories and rules through the JSON API (N17)
rather than editing a file directly. `group_uncategorized` builds the same
grouped rows the API's GET /api/uncategorized returns, so the text export
and the API always agree.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from sonar.importing.dedup import normalize_text
from sonar.transactions import ParsedTransaction

HEADER = "Categorization request: follow the Categorization workflow in CLAUDE.md."

_NO_COUNTERPARTY = "(no counterparty)"
_PURPOSE_MAX_LEN = 80
_MAX_SAMPLES = 2


@dataclass(frozen=True)
class UncategorizedGroup:
    """One counterparty group, shared by the text export and GET /api/uncategorized."""

    key: str
    count: int
    min_amount: str  # euro text, e.g. "-12.34"
    max_amount: str
    first_date: date
    last_date: date
    sample_purposes: list[str]


def group_uncategorized(txs: Iterable[ParsedTransaction]) -> list[UncategorizedGroup]:
    """Group by normalized counterparty, biggest groups first (ties alphabetical)."""
    buckets: dict[str, list[ParsedTransaction]] = defaultdict(list)
    for tx in txs:
        key = normalize_text(tx.counterparty) or _NO_COUNTERPARTY
        buckets[key].append(tx)

    ordered = sorted(buckets.items(), key=lambda item: (-len(item[1]), item[0]))
    return [_build_group(key, group) for key, group in ordered]


def _build_group(key: str, group: list[ParsedTransaction]) -> UncategorizedGroup:
    amounts = [tx.amount_cents for tx in group]
    dates = [tx.booking_date for tx in group]
    return UncategorizedGroup(
        key=key,
        count=len(group),
        min_amount=_format_cents(min(amounts)),
        max_amount=_format_cents(max(amounts)),
        first_date=min(dates),
        last_date=max(dates),
        sample_purposes=_sample_purposes(group),
    )


def build_categorization_request(txs: Iterable[ParsedTransaction]) -> str:
    """One self-contained block: header, then one line per counterparty group."""
    groups = group_uncategorized(txs)
    lines = [HEADER] + [_format_group(group) for group in groups]
    return "\n".join(lines)


def _format_group(group: UncategorizedGroup) -> str:
    amount_range = f"{group.min_amount}..{group.max_amount} EUR"
    date_range = f"{group.first_date.isoformat()}..{group.last_date.isoformat()}"
    samples = " / ".join(group.sample_purposes)
    return f"{group.count}x {group.key} | {amount_range} | {date_range} | {samples}"


def _sample_purposes(group: list[ParsedTransaction]) -> list[str]:
    # Up to 2 distinct purposes, in the order they first appear.
    seen: list[str] = []
    for tx in group:
        truncated = _truncate(tx.purpose)
        if truncated not in seen:
            seen.append(truncated)
        if len(seen) == _MAX_SAMPLES:
            break
    return seen


def _truncate(text: str) -> str:
    if len(text) <= _PURPOSE_MAX_LEN:
        return text
    return text[:_PURPOSE_MAX_LEN] + "…"


def _format_cents(cents: int) -> str:
    # Display-only conversion from integer cents; storage/comparisons never use float.
    sign = "-" if cents < 0 else ""
    whole, remainder = divmod(abs(cents), 100)
    return f"{sign}{whole}.{remainder:02d}"
