"""Tests for the migration runner and connection helper."""

import sqlite3

import pytest

from sonar.db import apply_migrations, connect


def _write(migrations_dir, name, sql):
    migrations_dir.mkdir(parents=True, exist_ok=True)
    (migrations_dir / name).write_text(sql)


def test_applies_migrations_in_order_and_creates_tables(tmp_path):
    migrations_dir = tmp_path / "migrations"
    _write(migrations_dir, "0001_accounts.sql", "CREATE TABLE accounts (id INTEGER PRIMARY KEY);")
    _write(
        migrations_dir,
        "0002_transactions.sql",
        "CREATE TABLE transactions (id INTEGER PRIMARY KEY, account_id INTEGER);",
    )

    conn = sqlite3.connect(":memory:")

    applied = apply_migrations(conn, migrations_dir)

    assert applied == ["0001_accounts.sql", "0002_transactions.sql"]
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"accounts", "transactions", "schema_migrations"} <= tables


def test_second_run_applies_nothing_and_keeps_data(tmp_path):
    migrations_dir = tmp_path / "migrations"
    _write(migrations_dir, "0001_accounts.sql", "CREATE TABLE accounts (id INTEGER PRIMARY KEY);")
    _write(
        migrations_dir,
        "0002_transactions.sql",
        "CREATE TABLE transactions (id INTEGER PRIMARY KEY, account_id INTEGER);",
    )

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, migrations_dir)
    conn.execute("INSERT INTO accounts (id) VALUES (1)")
    conn.commit()

    applied_again = apply_migrations(conn, migrations_dir)

    assert applied_again == []
    rows = conn.execute("SELECT id FROM accounts").fetchall()
    assert rows == [(1,)]


def test_adding_a_third_file_applies_only_that_file(tmp_path):
    migrations_dir = tmp_path / "migrations"
    _write(migrations_dir, "0001_accounts.sql", "CREATE TABLE accounts (id INTEGER PRIMARY KEY);")
    _write(
        migrations_dir,
        "0002_transactions.sql",
        "CREATE TABLE transactions (id INTEGER PRIMARY KEY, account_id INTEGER);",
    )

    conn = sqlite3.connect(":memory:")
    apply_migrations(conn, migrations_dir)

    _write(
        migrations_dir, "0003_categories.sql", "CREATE TABLE categories (id INTEGER PRIMARY KEY);"
    )

    applied = apply_migrations(conn, migrations_dir)

    assert applied == ["0003_categories.sql"]
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "categories" in tables


def test_missing_migrations_dir_means_no_migrations(tmp_path):
    conn = sqlite3.connect(":memory:")

    applied = apply_migrations(conn, tmp_path / "does_not_exist")

    assert applied == []


def test_failing_migration_is_not_recorded_as_applied(tmp_path):
    migrations_dir = tmp_path / "migrations"
    _write(migrations_dir, "0001_ok.sql", "CREATE TABLE ok (id INTEGER PRIMARY KEY);")
    _write(
        migrations_dir,
        "0002_broken.sql",
        "CREATE TABLE broken (id INTEGER PRIMARY KEY);"
        "CREATE TABLE broken (id INTEGER PRIMARY KEY);",
    )

    conn = sqlite3.connect(":memory:")

    with pytest.raises(sqlite3.Error):
        apply_migrations(conn, migrations_dir)

    applied_names = {row[0] for row in conn.execute("SELECT name FROM schema_migrations")}
    assert applied_names == {"0001_ok.sql"}
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "broken" not in tables


def test_connect_creates_parent_dir(tmp_path):
    db_path = tmp_path / "nested" / "sub" / "sonar.db"

    conn = connect(db_path)
    conn.execute("CREATE TABLE t (id INTEGER)")
    conn.commit()
    conn.close()

    assert db_path.parent.is_dir()
    assert db_path.exists()
