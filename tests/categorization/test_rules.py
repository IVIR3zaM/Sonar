"""Tests for the pure rule engine in sonar.categorization.rules (SPEC §5)."""

from __future__ import annotations

from datetime import date

import pytest

from sonar.categorization.rules import (
    Rule,
    categorize,
    load_taxonomy,
    match_rule,
    parse_taxonomy,
    validate_rule,
)
from sonar.transactions import ParsedTransaction


def _tx(
    counterparty: str = "Some Shop",
    purpose: str = "purchase",
    amount_cents: int = -1000,
    iban: str | None = None,
    creditor_id: str | None = None,
) -> ParsedTransaction:
    return ParsedTransaction(
        account="Girokonto",
        booking_date=date(2024, 1, 1),
        value_date=date(2024, 1, 1),
        amount_cents=amount_cents,
        currency="EUR",
        counterparty=counterparty,
        purpose=purpose,
        raw_row="raw",
        iban=iban,
        creditor_id=creditor_id,
    )


def test_first_match_wins() -> None:
    taxonomy = parse_taxonomy(
        """
        [[category]]
        name = "Groceries"
        type = "lights_on"

        [[category]]
        name = "Shopping"
        type = "lights_on"

        [[rule]]
        category = "Groceries"
        counterparty = "market"

        [[rule]]
        category = "Shopping"
        counterparty = "mart"
        """
    )
    tx = _tx(counterparty="Fresh Market GmbH")
    assert categorize(tx, taxonomy.rules) == "Groceries"


def test_substring_match_is_case_insensitive() -> None:
    taxonomy = parse_taxonomy(
        """
        [[category]]
        name = "Groceries"
        type = "lights_on"

        [[rule]]
        category = "Groceries"
        counterparty = "MARKET"
        """
    )
    assert categorize(_tx(counterparty="fresh market"), taxonomy.rules) == "Groceries"


def test_regex_condition_is_case_insensitive() -> None:
    taxonomy = parse_taxonomy(
        """
        [[category]]
        name = "Subscriptions"
        type = "fixed"

        [[rule]]
        category = "Subscriptions"
        purpose_regex = "netflix|spotify"
        """
    )
    assert categorize(_tx(purpose="Monthly SPOTIFY payment"), taxonomy.rules) == "Subscriptions"
    assert categorize(_tx(purpose="unrelated"), taxonomy.rules) is None


def test_sign_filter_debit_and_credit() -> None:
    taxonomy = parse_taxonomy(
        """
        [[category]]
        name = "Salary"
        type = "income"

        [[rule]]
        category = "Salary"
        counterparty = "employer"
        sign = "credit"
        """
    )
    assert categorize(_tx(counterparty="Employer Inc", amount_cents=250_000), taxonomy.rules) == (
        "Salary"
    )
    assert categorize(_tx(counterparty="Employer Inc", amount_cents=-500), taxonomy.rules) is None


def test_iban_filter_is_space_stripped_and_uppercased() -> None:
    taxonomy = parse_taxonomy(
        """
        [[category]]
        name = "Rent"
        type = "fixed"

        [[rule]]
        category = "Rent"
        purpose = "rent"
        iban = "DE89 3704 0044 0532 0130 00"
        """
    )
    tx = _tx(purpose="monthly rent", iban="de89370400440532013000")
    assert categorize(tx, taxonomy.rules) == "Rent"
    assert categorize(_tx(purpose="monthly rent", iban="DE00000000"), taxonomy.rules) is None


def test_creditor_id_filter() -> None:
    taxonomy = parse_taxonomy(
        """
        [[category]]
        name = "Insurance"
        type = "fixed"

        [[rule]]
        category = "Insurance"
        purpose = "premium"
        creditor_id = "DE98ZZZ09999999999"
        """
    )
    tx = _tx(purpose="insurance premium", creditor_id="DE98ZZZ09999999999")
    assert categorize(tx, taxonomy.rules) == "Insurance"
    assert categorize(_tx(purpose="insurance premium", creditor_id="OTHER"), taxonomy.rules) is None


def test_no_match_returns_none() -> None:
    taxonomy = parse_taxonomy(
        """
        [[category]]
        name = "Groceries"
        type = "lights_on"

        [[rule]]
        category = "Groceries"
        counterparty = "market"
        """
    )
    assert match_rule(_tx(counterparty="Bookshop"), taxonomy.rules) is None
    assert categorize(_tx(counterparty="Bookshop"), taxonomy.rules) is None


def test_unknown_category_type_raises() -> None:
    with pytest.raises(ValueError, match="unknown type"):
        parse_taxonomy(
            """
            [[category]]
            name = "Weird"
            type = "bogus"
            """
        )


def test_rule_naming_undefined_category_raises() -> None:
    with pytest.raises(ValueError, match="undefined category"):
        parse_taxonomy(
            """
            [[rule]]
            category = "Ghost"
            counterparty = "market"
            """
        )


def test_rule_without_text_condition_raises() -> None:
    with pytest.raises(ValueError, match="no text condition"):
        parse_taxonomy(
            """
            [[category]]
            name = "Groceries"
            type = "lights_on"

            [[rule]]
            category = "Groceries"
            sign = "debit"
            """
        )


def test_bad_regex_raises() -> None:
    with pytest.raises(ValueError, match="bad regex"):
        parse_taxonomy(
            """
            [[category]]
            name = "Groceries"
            type = "lights_on"

            [[rule]]
            category = "Groceries"
            purpose_regex = "("
            """
        )


def test_amount_range_filter_is_inclusive_on_absolute_amount() -> None:
    taxonomy = parse_taxonomy(
        """
        [[category]]
        name = "Hosting"
        type = "fixed"

        [[category]]
        name = "Friend loan"
        type = "fixed"

        [[rule]]
        category = "Hosting"
        purpose = "hoster"
        max_amount_cents = 2500

        [[rule]]
        category = "Friend loan"
        purpose = "hoster"
        min_amount_cents = 2501
        """
    )
    assert (
        categorize(_tx(purpose="hoster invoice", amount_cents=-1146), taxonomy.rules) == "Hosting"
    )
    assert (
        categorize(_tx(purpose="hoster invoice", amount_cents=-2500), taxonomy.rules) == "Hosting"
    )
    assert (
        categorize(_tx(purpose="hoster invoice", amount_cents=-2501), taxonomy.rules)
        == "Friend loan"
    )
    assert (
        categorize(_tx(purpose="hoster invoice", amount_cents=-8570), taxonomy.rules)
        == "Friend loan"
    )
    assert categorize(_tx(purpose="hoster refund", amount_cents=1146), taxonomy.rules) == "Hosting"


@pytest.mark.parametrize(
    "bounds,message",
    [
        ("min_amount_cents = -1", "must be a non-negative integer"),
        ('max_amount_cents = "25"', "must be a non-negative integer"),
        ("min_amount_cents = 12.5", "must be a non-negative integer"),
        ("min_amount_cents = 3000\nmax_amount_cents = 2000", "min_amount_cents above"),
    ],
)
def test_bad_amount_range_raises(bounds: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        parse_taxonomy(
            f"""
[[category]]
name = "Groceries"
type = "lights_on"

[[rule]]
category = "Groceries"
counterparty = "market"
{bounds}
"""
        )


def test_bad_sign_raises() -> None:
    with pytest.raises(ValueError, match="unknown sign"):
        parse_taxonomy(
            """
            [[category]]
            name = "Groceries"
            type = "lights_on"

            [[rule]]
            category = "Groceries"
            counterparty = "market"
            sign = "sideways"
            """
        )


def test_load_taxonomy_reads_a_file(tmp_path) -> None:
    toml_path = tmp_path / "categories.toml"
    toml_path.write_text(
        """
        [[category]]
        name = "Groceries"
        type = "lights_on"

        [[rule]]
        category = "Groceries"
        counterparty = "market"
        """,
        encoding="utf-8",
    )
    taxonomy = load_taxonomy(toml_path)
    assert taxonomy.categories == {"Groceries": "lights_on"}
    assert categorize(_tx(counterparty="Local Market"), taxonomy.rules) == "Groceries"


def test_parse_taxonomy_accepts_lights_on_and_occasional_types() -> None:
    taxonomy = parse_taxonomy(
        """
        [[category]]
        name = "Transport"
        type = "lights_on"

        [[category]]
        name = "Dining"
        type = "occasional"
        """
    )
    assert taxonomy.categories == {"Transport": "lights_on", "Dining": "occasional"}


def test_legacy_variable_type_maps_by_category_name() -> None:
    taxonomy = parse_taxonomy(
        """
        [[category]]
        name = "Groceries"
        type = "variable"

        [[category]]
        name = "Dining"
        type = "variable"
        """
    )
    assert taxonomy.categories == {"Groceries": "lights_on", "Dining": "occasional"}


def test_validate_rule_matches_the_toml_path() -> None:
    categories = {"Groceries": "lights_on"}
    raw = {"category": "Groceries", "counterparty": "market"}
    assert validate_rule(raw, categories) == Rule(category="Groceries", counterparty="market")


def test_validate_rule_bad_purpose_regex_names_the_field() -> None:
    with pytest.raises(ValueError, match="bad regex in purpose_regex"):
        validate_rule({"category": "Groceries", "purpose_regex": "("}, {"Groceries": "lights_on"})
