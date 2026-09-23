"""Pure rule engine for categorization (SPEC §5).

Categories and rules live in `categories.toml`. Rules are ordered and the
first whose conditions all match (AND) wins. Rules are re-applied to every
stored transaction on each import and at startup, so regexes are compiled
once here, at parse time, rather than on every match.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from sonar.transactions import ParsedTransaction

CATEGORY_TYPES = {"income", "fixed", "variable", "transfer"}
SIGNS = {"debit", "credit"}


@dataclass(frozen=True)
class Rule:
    """One ordered rule; `category` must name an entry in the taxonomy."""

    category: str
    counterparty: str | None = None
    counterparty_regex: re.Pattern[str] | None = None
    purpose: str | None = None
    purpose_regex: re.Pattern[str] | None = None
    sign: str | None = None  # "debit" or "credit"
    iban: str | None = None  # normalized: space-stripped, uppercase
    creditor_id: str | None = None


@dataclass(frozen=True)
class Taxonomy:
    categories: dict[str, str]  # name -> type
    rules: tuple[Rule, ...]


def parse_taxonomy(toml_text: str) -> Taxonomy:
    """Parse `categories.toml` content into a Taxonomy, raising ValueError on a bad schema."""
    data = tomllib.loads(toml_text)
    categories = _parse_categories(data.get("category", []))
    rules = tuple(_parse_rule(raw, categories) for raw in data.get("rule", []))
    return Taxonomy(categories=categories, rules=rules)


def load_taxonomy(path: Path) -> Taxonomy:
    return parse_taxonomy(Path(path).read_text(encoding="utf-8"))


def match_rule(tx: ParsedTransaction, rules: tuple[Rule, ...]) -> Rule | None:
    """Return the first rule whose conditions all match, or None."""
    for rule in rules:
        if _matches(tx, rule):
            return rule
    return None


def categorize(tx: ParsedTransaction, rules: tuple[Rule, ...]) -> str | None:
    rule = match_rule(tx, rules)
    return rule.category if rule is not None else None


def _parse_categories(raw_categories: list[dict]) -> dict[str, str]:
    categories: dict[str, str] = {}
    for raw in raw_categories:
        name = raw["name"]
        category_type = raw["type"]
        if category_type not in CATEGORY_TYPES:
            raise ValueError(f"category {name!r} has unknown type {category_type!r}")
        categories[name] = category_type
    return categories


def _parse_rule(raw: dict, categories: dict[str, str]) -> Rule:
    category = raw["category"]
    if category not in categories:
        raise ValueError(f"rule names undefined category {category!r}")

    counterparty = raw.get("counterparty")
    purpose = raw.get("purpose")
    counterparty_regex_text = raw.get("counterparty_regex")
    purpose_regex_text = raw.get("purpose_regex")
    if not any((counterparty, purpose, counterparty_regex_text, purpose_regex_text)):
        raise ValueError(f"rule for {category!r} has no text condition")

    sign = raw.get("sign")
    if sign is not None and sign not in SIGNS:
        raise ValueError(f"rule for {category!r} has unknown sign {sign!r}")

    try:
        counterparty_regex = (
            re.compile(counterparty_regex_text, re.IGNORECASE) if counterparty_regex_text else None
        )
        purpose_regex = (
            re.compile(purpose_regex_text, re.IGNORECASE) if purpose_regex_text else None
        )
    except re.error as exc:
        raise ValueError(f"rule for {category!r} has a bad regex: {exc}") from exc

    iban = raw.get("iban")
    return Rule(
        category=category,
        counterparty=counterparty,
        counterparty_regex=counterparty_regex,
        purpose=purpose,
        purpose_regex=purpose_regex,
        sign=sign,
        iban=_normalize_iban(iban) if iban else None,
        creditor_id=raw.get("creditor_id"),
    )


def _matches(tx: ParsedTransaction, rule: Rule) -> bool:
    if (
        rule.counterparty is not None
        and rule.counterparty.casefold() not in tx.counterparty.casefold()
    ):
        return False
    if rule.counterparty_regex is not None and not rule.counterparty_regex.search(tx.counterparty):
        return False
    if rule.purpose is not None and rule.purpose.casefold() not in tx.purpose.casefold():
        return False
    if rule.purpose_regex is not None and not rule.purpose_regex.search(tx.purpose):
        return False
    if rule.sign is not None:
        is_debit = tx.amount_cents < 0
        if rule.sign == "debit" and not is_debit:
            return False
        if rule.sign == "credit" and is_debit:
            return False
    if rule.iban is not None and rule.iban != _normalize_iban(tx.iban or ""):
        return False
    if rule.creditor_id is not None and rule.creditor_id != tx.creditor_id:
        return False
    return True


def _normalize_iban(iban: str) -> str:
    return iban.replace(" ", "").upper()
