"""Sonar entry point: one-command start, plus the `import-categories` CLI."""

import argparse
import sys
from datetime import date
from pathlib import Path

import uvicorn

from sonar.categorization.rules import load_taxonomy
from sonar.categorization.store import reapply_rules, replace_taxonomy, uncategorized_count
from sonar.db import MIGRATIONS_DIR, apply_migrations, connect
from sonar.recurring.store import sync_detected
from sonar.web.app import create_app


def main() -> None:
    """Start the Sonar web app on 127.0.0.1:8000, or run the `import-categories` subcommand.

    Only `sys.argv[1]` being literally "import-categories" is treated as the
    CLI; any other invocation (including none) starts the server, so this
    stays the console-script entry point without full argparse swallowing an
    unrelated process argv (e.g. a test runner's own flags).
    """
    argv = sys.argv[1:]
    if argv and argv[0] == "import-categories":
        args = _parse_import_categories_args(argv[1:])
        import_categories(Path(args.path), Path(args.db))
        return
    app = create_app()
    uvicorn.run(app, host="127.0.0.1", port=8000)


def _parse_import_categories_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="sonar import-categories")
    parser.add_argument("path")
    parser.add_argument("--db", default="data/sonar.db")
    return parser.parse_args(argv)


def import_categories(path: Path, db_path: Path) -> None:
    """Migrate `db_path` and replace its stored taxonomy with `path`'s TOML.

    Re-applies the new rules and re-runs recurring-payment detection, then
    prints one line with the category, rule and uncategorized counts. A
    missing file or a bad TOML schema prints the message and exits 1,
    leaving the DB unchanged.
    """
    try:
        taxonomy = load_taxonomy(path)
    except (OSError, ValueError) as error:
        print(error)
        raise SystemExit(1) from None

    conn = connect(db_path)
    try:
        apply_migrations(conn, MIGRATIONS_DIR)
        replace_taxonomy(conn, taxonomy)
        reapply_rules(conn, taxonomy.rules)
        sync_detected(conn, taxonomy.categories, date.today())
        uncategorized = uncategorized_count(conn)
    finally:
        conn.close()
    print(
        f"Imported {len(taxonomy.categories)} categories and {len(taxonomy.rules)} rules; "
        f"{uncategorized} uncategorized."
    )


if __name__ == "__main__":
    main()
