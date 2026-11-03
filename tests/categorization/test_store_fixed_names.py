"""Fixed category choices for manual payments."""

import sqlite3

from sonar.categorization.store import add_category, fixed_category_names
from sonar.db import MIGRATIONS_DIR, apply_migrations


def test_fixed_category_names_are_sorted_and_exclude_other_groups():
    with sqlite3.connect(":memory:") as conn:
        apply_migrations(conn, MIGRATIONS_DIR)
        conn.execute("DELETE FROM category_rules")
        conn.execute("DELETE FROM categories")
        assert fixed_category_names(conn) == []
        add_category(conn, "Subscriptions", "fixed")
        add_category(conn, "Housing", "fixed")
        add_category(conn, "Loans", "fixed", debt=True)
        for group in ("income", "transfer", "lights_on", "occasional"):
            add_category(conn, group, group)
        assert fixed_category_names(conn) == ["Housing", "Loans", "Subscriptions"]
