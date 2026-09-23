"""Fingerprints that let re-imports skip rows already stored (SPEC §4 Idempotency).

Genuinely identical rows (two equal purchases on one day) share a fingerprint,
so each row is also numbered by occurrence; `(fingerprint, occurrence)` is the
unique key. Re-importing the same rows in any order yields the same key set.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable
from typing import NamedTuple

from sonar.transactions import ParsedTransaction


class NumberedTransaction(NamedTuple):
    transaction: ParsedTransaction
    fingerprint: str
    occurrence: int


def fingerprint(tx: ParsedTransaction) -> str:
    """Hash the fields that identify a booking, ignoring cosmetic text differences."""
    fields = [
        normalize_text(tx.account),
        tx.booking_date.isoformat(),
        tx.amount_cents,
        normalize_text(tx.counterparty),
        normalize_text(tx.purpose),
    ]
    # A JSON array keeps field boundaries explicit, so "ab"+"c" never equals "a"+"bc".
    encoded = json.dumps(fields, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def number_occurrences(txs: Iterable[ParsedTransaction]) -> list[NumberedTransaction]:
    """Pair each transaction with its fingerprint and its 1-based count among equals."""
    seen: Counter[str] = Counter()
    numbered = []
    for tx in txs:
        fp = fingerprint(tx)
        seen[fp] += 1
        numbered.append(NumberedTransaction(tx, fp, seen[fp]))
    return numbered


def normalize_text(text: str) -> str:
    # Exports of the same booking differ in case and spacing (padding, line wraps).
    return " ".join(text.casefold().split())
