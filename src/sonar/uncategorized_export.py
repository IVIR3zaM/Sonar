"""Build the copy-to-Claude-Code export for uncategorized transactions (SPEC §5).

The "Uncategorized" page turns unmatched rows into one compact text block. I
paste it into Claude Code to extend `categories.toml`; the exact first line
below is what tells Claude Code which workflow to run.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

from sonar.dedup import normalize_text
from sonar.transactions import ParsedTransaction

HEADER = "Categorization request: follow the Categorization workflow in CLAUDE.md."

_NO_COUNTERPARTY = "(no counterparty)"
_PURPOSE_MAX_LEN = 80
_MAX_SAMPLES = 2


def build_categorization_request(txs: Iterable[ParsedTransaction]) -> str:
    """One self-contained block: header, then one line per counterparty group."""
    groups: dict[str, list[ParsedTransaction]] = defaultdict(list)
    for tx in txs:
        key = normalize_text(tx.counterparty) or _NO_COUNTERPARTY
        groups[key].append(tx)

    # Biggest groups first (they matter most), ties broken alphabetically for stable output.
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    lines = [HEADER] + [_format_group(key, group) for key, group in ordered]
    return "\n".join(lines)


def _format_group(key: str, group: list[ParsedTransaction]) -> str:
    amounts = [tx.amount_cents for tx in group]
    dates = [tx.booking_date for tx in group]
    samples = _sample_purposes(group)
    amount_range = f"{_format_cents(min(amounts))}..{_format_cents(max(amounts))} EUR"
    date_range = f"{min(dates).isoformat()}..{max(dates).isoformat()}"
    return f"{len(group)}x {key} | {amount_range} | {date_range} | {' / '.join(samples)}"


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
