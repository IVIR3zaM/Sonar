"""Table-driven tests for the rule engine (`rules.match_rule`, SPEC §5).

Categories and rules now live only in the DB (N05); there is no shipped
`categories.toml` to test against (N11). This file builds its own small,
fake taxonomy -- fake names, the standard example IBAN, a fake creditor ID
-- stores it in an in-memory DB the same way the Categories page and the
`import-categories` CLI do (`store.replace_taxonomy`), and reads it
back through `load_stored_taxonomy` before matching. No value from an
owner's local `data/categories.toml` belongs here.
"""

from __future__ import annotations

import sqlite3
from datetime import date

import pytest

from sonar.categorization.rules import Rule, Taxonomy, match_rule, parse_taxonomy
from sonar.categorization.store import list_rules, load_stored_taxonomy, move_rule, replace_taxonomy
from sonar.db import MIGRATIONS_DIR, apply_migrations
from sonar.transactions import ParsedTransaction

# A widely published example IBAN (Deutsche Bundesbank's own sample), never a
# real account; the creditor ID below is fabricated in the same style.
_EXAMPLE_IBAN = "DE89 3704 0044 0532 0130 00"
_EXAMPLE_CREDITOR_ID = "DE00ZZZ00000000042"

FAKE_TOML = f"""
[[category]]
name = "Salary"
type = "income"

[[category]]
name = "Own transfers"
type = "transfer"

[[category]]
name = "Mortgage"
type = "fixed"

[[category]]
name = "Loans & Installments"
type = "fixed"

[[category]]
name = "Utilities"
type = "fixed"

[[category]]
name = "Groceries"
type = "lights_on"

[[category]]
name = "Dining"
type = "occasional"

[[category]]
name = "Fees & Taxes"
type = "occasional"

[[rule]]
category = "Mortgage"
purpose_regex = "^"
iban = "{_EXAMPLE_IBAN}"
sign = "debit"

[[rule]]
category = "Loans & Installments"
purpose_regex = "^"
creditor_id = "{_EXAMPLE_CREDITOR_ID}"
sign = "debit"

[[rule]]
category = "Salary"
purpose_regex = "wages"
sign = "credit"

[[rule]]
category = "Own transfers"
counterparty = "Fake Holder"
sign = "credit"

[[rule]]
category = "Utilities"
counterparty = "Fake Holder"
sign = "debit"

[[rule]]
category = "Groceries"
counterparty = "Fake Grocer"

[[rule]]
category = "Dining"
purpose = "restaurant"
min_amount_cents = 500
max_amount_cents = 5000

[[rule]]
category = "Fees & Taxes"
purpose = "restaurant"
min_amount_cents = 5001
"""

# A second, disjoint fixture used only to test that `match_rule` follows the
# DB's rule order and that a `move_rule` re-ordering is reflected on reload.
MOVE_TOML = """
[[category]]
name = "Category A"
type = "lights_on"

[[category]]
name = "Category B"
type = "occasional"

[[rule]]
category = "Category A"
counterparty = "Fake Overlap Merchant"
sign = "debit"

[[rule]]
category = "Category B"
counterparty = "Fake Overlap Merchant"
sign = "debit"
"""


def _tx(
    counterparty: str = "Some Shop",
    purpose: str = "purchase",
    amount_cents: int = -1000,
    iban: str | None = None,
    creditor_id: str | None = None,
) -> ParsedTransaction:
    return ParsedTransaction(
        account="Girokonto",
        booking_date=date(2026, 1, 15),
        value_date=date(2026, 1, 15),
        amount_cents=amount_cents,
        currency="EUR",
        counterparty=counterparty,
        purpose=purpose,
        raw_row="raw",
        iban=iban,
        creditor_id=creditor_id,
    )


@pytest.fixture(scope="module")
def taxonomy() -> Taxonomy:
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    replace_taxonomy(conn, parse_taxonomy(FAKE_TOML))
    return load_stored_taxonomy(conn)


# (counterparty, purpose, amount_cents, iban, creditor_id) -> expected category
CASES: tuple[tuple[str, str, int, str | None, str | None, str], ...] = (
    # substring match
    ("Fake Grocer Berlin", "Weekly shop", -2_500, None, None, "Groceries"),
    # regex match, combined with a sign condition
    ("Fake Employer GmbH", "WAGES PAYMENT 09/26", 250_000, None, None, "Salary"),
    # sign tells apart two rules that share the same counterparty text
    ("Fake Holder", "Transfer between own accounts", 5_000, None, None, "Own transfers"),
    ("Fake Holder", "Bill payment", -3_000, None, None, "Utilities"),
    # IBAN beats a same-counterparty rule that comes later in the order
    (
        "Fake Holder",
        "Loan installment",
        -60_000,
        _EXAMPLE_IBAN,
        None,
        "Mortgage",
    ),
    # creditor ID beats a same-counterparty rule that comes later in the order
    (
        "Fake Holder",
        "Loan installment collection",
        -30_000,
        None,
        _EXAMPLE_CREDITOR_ID,
        "Loans & Installments",
    ),
    # amount range tells apart two rules that share the same purpose text
    ("Some Bistro", "restaurant bill", -1_200, None, None, "Dining"),
    ("Some Authority", "restaurant fee audit", -9_000, None, None, "Fees & Taxes"),
)


@pytest.mark.parametrize("counterparty,purpose,amount_cents,iban,creditor_id,expected", CASES)
def test_case_matches_expected_category(
    taxonomy: Taxonomy,
    counterparty: str,
    purpose: str,
    amount_cents: int,
    iban: str | None,
    creditor_id: str | None,
    expected: str,
) -> None:
    tx = _tx(counterparty, purpose, amount_cents, iban, creditor_id)
    rule = match_rule(tx, taxonomy.rules)
    assert rule is not None
    assert rule.category == expected


def test_fixture_taxonomy_loads(taxonomy: Taxonomy) -> None:
    assert len(taxonomy.categories) == 8
    assert len(taxonomy.rules) == 8


def _tx_for_rule(rule: Rule) -> ParsedTransaction:
    """Build a transaction that satisfies exactly `rule`'s own stored conditions."""
    if rule.counterparty is not None:
        counterparty = rule.counterparty
    elif rule.counterparty_regex is not None:
        counterparty = rule.counterparty_regex.pattern
    else:
        counterparty = "Some Shop"

    if rule.purpose is not None:
        purpose = rule.purpose
    elif rule.purpose_regex is not None:
        purpose = rule.purpose_regex.pattern
    else:
        purpose = "purchase"

    size = 1_000
    if rule.min_amount_cents is not None:
        size = max(size, rule.min_amount_cents)
    if rule.max_amount_cents is not None:
        size = min(size, rule.max_amount_cents)
    amount_cents = size if rule.sign == "credit" else -size
    return _tx(
        counterparty=counterparty,
        purpose=purpose,
        amount_cents=amount_cents,
        iban=rule.iban,
        creditor_id=rule.creditor_id,
    )


def test_every_rule_is_reachable(taxonomy: Taxonomy) -> None:
    """Every rule in the fixture is the match_rule hit of some transaction."""
    for index, rule in enumerate(taxonomy.rules):
        tx = _tx_for_rule(rule)
        hit = match_rule(tx, taxonomy.rules)
        assert hit is rule, f"rule {index} ({rule.category!r}) is unreachable or shadowed"


def test_match_follows_order_after_a_store_move() -> None:
    """The first matching rule wins, and a `move_rule` re-order changes that winner."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    replace_taxonomy(conn, parse_taxonomy(MOVE_TOML))

    tx = _tx(counterparty="Fake Overlap Merchant", purpose="purchase", amount_cents=-1_000)
    before = load_stored_taxonomy(conn)
    hit = match_rule(tx, before.rules)
    assert hit is not None and hit.category == "Category A"

    stored_rules = list_rules(conn)
    (rule_b,) = [r for r in stored_rules if r.category == "Category B"]
    move_rule(conn, rule_b.id, 1)

    after = load_stored_taxonomy(conn)
    hit = match_rule(tx, after.rules)
    assert hit is not None and hit.category == "Category B"


def test_generic_seed_has_expected_groups_and_no_rules() -> None:
    """A freshly migrated DB seeds only the N02 groups (SPEC §5, §13), with no rules."""
    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, MIGRATIONS_DIR)
    taxonomy = load_stored_taxonomy(conn)
    assert taxonomy.rules == ()
    assert taxonomy.categories["Housing"] == "fixed"
    assert taxonomy.categories["Groceries"] == "lights_on"
    assert taxonomy.categories["Transport"] == "lights_on"
    assert taxonomy.categories["Shopping"] == "lights_on"
    assert taxonomy.categories["Dining"] == "occasional"
