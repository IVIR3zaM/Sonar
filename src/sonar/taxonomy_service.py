"""The one service layer between HTTP input and `taxonomy_store`.

Shared by the Categories page (N08, N09) and the JSON API (N17): both call
these functions and nothing in `taxonomy_store` directly, so validation and
error messages exist in exactly one place. For now this holds the one
function the app's routes and the CLI share: reload the taxonomy stored in
the DB, re-apply its rules to every transaction, and re-run recurring-payment
detection.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from sonar.categorizing import reapply_rules, uncategorized_count
from sonar.recurring import sync_detected
from sonar.taxonomy_store import load_stored_taxonomy


def reapply_stored_taxonomy(conn: sqlite3.Connection, today: date) -> int:
    """Re-apply the DB's own rules and re-sync detected payments; return the uncategorized count."""
    taxonomy = load_stored_taxonomy(conn)
    reapply_rules(conn, taxonomy.rules)
    sync_detected(conn, taxonomy.categories, today)
    return uncategorized_count(conn)
