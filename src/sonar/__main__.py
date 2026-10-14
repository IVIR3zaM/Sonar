"""Sonar entry point: one-command start, plus the `import-categories`, allow-list and
`bank-sync` CLIs."""

import argparse
import copy
import logging
import os
import sys
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import uvicorn
from uvicorn.config import LOGGING_CONFIG

from sonar.auth import store as auth_store
from sonar.auth.emails import normalize_email
from sonar.auth.settings import AuthSettings, auth_settings
from sonar.banking.client import BankApiError, EnableBankingClient, default_http
from sonar.banking.service import NotConnectedError, SyncClient, sync
from sonar.banking.settings import BankSettings, bank_settings, read_private_key
from sonar.categorization.rules import load_taxonomy
from sonar.categorization.store import reapply_rules, replace_taxonomy, uncategorized_count
from sonar.db import MIGRATIONS_DIR, apply_migrations, connect
from sonar.recurring.store import sync_detected
from sonar.web.app import STATIC_DIR, create_app


def main() -> None:
    """Start the Sonar web app on 127.0.0.1 (SONAR_PORT, else 8000), or run a CLI subcommand.

    Only `sys.argv[1]` being literally a subcommand name (`import-categories`,
    `allow-email`, `revoke-email`, `list-emails`, `sync-emails`, `bank-sync`) is treated as
    the CLI; any other invocation (including none) starts the server, so this
    stays the console-script entry point without full argparse swallowing an
    unrelated process argv (e.g. a test runner's own flags).
    """
    argv = sys.argv[1:]
    if argv and argv[0] == "import-categories":
        args = _parse_import_categories_args(argv[1:])
        import_categories(Path(args.path), Path(args.db))
        return
    if argv and argv[0] == "allow-email":
        args = _parse_email_args("allow-email", argv[1:])
        allow_email(args.email, Path(args.db))
        return
    if argv and argv[0] == "revoke-email":
        args = _parse_email_args("revoke-email", argv[1:])
        revoke_email(args.email, Path(args.db))
        return
    if argv and argv[0] == "list-emails":
        args = _parse_list_emails_args(argv[1:])
        list_emails(Path(args.db))
        return
    if argv and argv[0] == "sync-emails":
        args = _parse_sync_emails_args(argv[1:])
        sync_emails(args.emails, Path(args.db))
        return
    if argv and argv[0] == "bank-sync":
        args = _parse_bank_sync_args(argv[1:])
        _, client = _bank()
        bank_sync(Path(args.db), client, date.today(), datetime.now(UTC))
        return
    serve()


def serve() -> None:
    """Run the web app; a partly configured sign-in or bank sync refuses to start (SPEC §13)."""
    auth = _auth_settings()
    bank, bank_client = _bank()
    app = create_app(_default_db_path(), auth=auth, bank=bank, bank_client=bank_client)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("SONAR_PORT") or "8000"),
        # Behind a reverse proxy on the same host, trust its X-Forwarded-* so
        # redirects and cookies see the public https scheme.
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        log_config=_access_log_config(),
    )


def _without_query(path: str) -> str:
    return path.split("?", 1)[0]


class _QueryFreeAccessLog(logging.Filter):
    """Drop the query from an access record's path (uvicorn's 3rd arg).

    The OAuth `code` and `state` arrive in the query of the bank and Google callbacks and
    are secrets, so no access line may carry them.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) == 5:
            client, method, path, http_version, status = record.args
            record.args = (client, method, _without_query(str(path)), http_version, status)
        return True


def _access_log_config() -> dict[str, Any]:
    """uvicorn's default logging with the query-free filter on the access handler."""
    config = copy.deepcopy(LOGGING_CONFIG)
    config["filters"] = {"query_free": {"()": _QueryFreeAccessLog}}
    config["handlers"]["access"]["filters"] = ["query_free"]
    return config


def _auth_settings() -> AuthSettings | None:
    try:
        return auth_settings(os.environ)
    except ValueError as error:
        print(error)
        raise SystemExit(1) from None


def _bank() -> tuple[BankSettings | None, EnableBankingClient | None]:
    """The bank settings and a client for them; (None, None) when bank sync is off."""
    try:
        bank = bank_settings(os.environ)
        if bank is None:
            return None, None
        private_key = read_private_key(bank.key_path, STATIC_DIR)
    except ValueError as error:
        print(error)
        raise SystemExit(1) from None
    now = lambda: datetime.now(UTC)  # noqa: E731
    return bank, EnableBankingClient(bank.app_id, private_key, default_http(), now)


def _default_db_path() -> Path:
    """The DB every command uses unless `--db` says otherwise; read at call time."""
    return Path(os.environ.get("SONAR_DB_PATH", "data/sonar.db"))


def _parse_import_categories_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="sonar import-categories")
    parser.add_argument("path")
    parser.add_argument("--db", default=_default_db_path())
    return parser.parse_args(argv)


def _parse_email_args(command: str, argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=f"sonar {command}")
    parser.add_argument("email")
    parser.add_argument("--db", default=_default_db_path())
    return parser.parse_args(argv)


def _parse_list_emails_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="sonar list-emails")
    parser.add_argument("--db", default=_default_db_path())
    return parser.parse_args(argv)


def _parse_sync_emails_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="sonar sync-emails")
    parser.add_argument("emails", nargs="+", metavar="email")
    parser.add_argument("--db", default=_default_db_path())
    return parser.parse_args(argv)


def _parse_bank_sync_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="sonar bank-sync")
    parser.add_argument("--db", default=_default_db_path())
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


def allow_email(email: str, db_path: Path) -> None:
    def action(conn: Any) -> str:
        auth_store.allow_email(conn, email, datetime.now(UTC))
        return f"Allowed {normalize_email(email)}."

    _run_on_allow_list(db_path, action)


def revoke_email(email: str, db_path: Path) -> None:
    def action(conn: Any) -> str:
        normalized = normalize_email(email)
        if auth_store.revoke_email(conn, email):
            return f"Revoked {normalized}."
        return f"{normalized} was not on the list."

    _run_on_allow_list(db_path, action)


def list_emails(db_path: Path) -> None:
    _run_on_allow_list(db_path, lambda conn: "\n".join(auth_store.list_emails(conn)))


def sync_emails(emails: list[str], db_path: Path) -> None:
    def action(conn: Any) -> str:
        auth_store.sync_emails(conn, emails, datetime.now(UTC))
        return f"Allowed exactly {len(auth_store.list_emails(conn))} email(s)."

    _run_on_allow_list(db_path, action)


def bank_sync(db_path: Path, client: SyncClient | None, today: date, now: datetime) -> None:
    """Sync the connected bank account into `db_path` and print one line.

    Bank sync off or no connection prints why and exits 0; a failed sync prints the client's
    fixed-shape message (never a key, token or session id) and exits 1.
    """
    if client is None:
        print("Bank sync is not configured.")
        return
    with closing(connect(db_path)) as conn:
        apply_migrations(conn, MIGRATIONS_DIR)
        try:
            result = sync(conn, client, today, now)
        except NotConnectedError:
            print("Bank is not connected.")
            return
        except BankApiError as error:
            print(f"Bank sync failed: {error.message}")
            raise SystemExit(1) from None
    balance = (
        f"balance {_format_cents(result.balance.amount_cents)} on {result.balance.as_of}"
        if result.balance
        else "no balance"
    )
    print(f"Bank sync: {result.added} added, {result.duplicates} duplicates, {balance}.")


def _format_cents(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, remainder = divmod(abs(cents), 100)
    return f"{sign}{whole}.{remainder:02d}"


def _run_on_allow_list(db_path: Path, action: Callable[[Any], str]) -> None:
    """Migrate `db_path`, run `action` and print its line.

    An invalid email prints the message and exits 1; the store has changed
    nothing by then.
    """
    with closing(connect(db_path)) as conn:
        apply_migrations(conn, MIGRATIONS_DIR)
        try:
            message = action(conn)
        except ValueError as error:
            print(error)
            raise SystemExit(1) from None
    if message:
        print(message)


if __name__ == "__main__":
    main()
