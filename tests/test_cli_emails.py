"""Tests for the allow-list CLI: allow-email, revoke-email, list-emails, sync-emails (SPEC §13)."""

import sqlite3

import pytest

from sonar.__main__ import main


def _run(monkeypatch, *args: str) -> None:
    monkeypatch.setattr("sys.argv", ["sonar", *args])
    main()


def _stored(db_path) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        return [r[0] for r in conn.execute("SELECT email FROM allowed_emails ORDER BY email")]
    finally:
        conn.close()


@pytest.fixture
def db(tmp_path, monkeypatch):
    monkeypatch.delenv("SONAR_DB_PATH", raising=False)
    return tmp_path / "t.db"


def test_allow_then_list_prints_the_email(db, monkeypatch, capsys):
    _run(monkeypatch, "allow-email", " Owner@Example.com ", "--db", str(db))
    _run(monkeypatch, "list-emails", "--db", str(db))

    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == "Allowed owner@example.com."
    assert lines[1:] == ["owner@example.com"]


def test_list_prints_one_email_per_line_sorted(db, monkeypatch, capsys):
    _run(monkeypatch, "sync-emails", "b@example.com", "a@example.com", "--db", str(db))
    capsys.readouterr()

    _run(monkeypatch, "list-emails", "--db", str(db))

    assert capsys.readouterr().out.splitlines() == ["a@example.com", "b@example.com"]


def test_revoke_a_listed_email(db, monkeypatch, capsys):
    _run(monkeypatch, "allow-email", "owner@example.com", "--db", str(db))
    capsys.readouterr()

    _run(monkeypatch, "revoke-email", "Owner@example.com", "--db", str(db))

    assert capsys.readouterr().out.strip() == "Revoked owner@example.com."
    assert _stored(db) == []


def test_revoke_an_unlisted_email_says_so_and_exits_0(db, monkeypatch, capsys):
    _run(monkeypatch, "revoke-email", "nobody@example.com", "--db", str(db))

    assert "was not on the list" in capsys.readouterr().out
    assert _stored(db) == []


def test_sync_replaces_the_set(db, monkeypatch, capsys):
    _run(monkeypatch, "allow-email", "old@example.com", "--db", str(db))
    _run(monkeypatch, "allow-email", "keep@example.com", "--db", str(db))

    _run(monkeypatch, "sync-emails", "keep@example.com", "new@example.com", "--db", str(db))

    assert _stored(db) == ["keep@example.com", "new@example.com"]
    assert "Allowed exactly 2 email(s)." in capsys.readouterr().out


@pytest.mark.parametrize(
    "command",
    [["allow-email", "nobody"], ["revoke-email", "a@b@example.com"], ["sync-emails", "x@"]],
)
def test_invalid_email_exits_1_with_the_table_unchanged(db, monkeypatch, capsys, command):
    _run(monkeypatch, "allow-email", "keep@example.com", "--db", str(db))
    capsys.readouterr()

    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, *command, "--db", str(db))

    assert excinfo.value.code == 1
    assert "not a valid email" in capsys.readouterr().out
    assert _stored(db) == ["keep@example.com"]


def test_sync_without_an_email_exits_2(db, monkeypatch):
    with pytest.raises(SystemExit) as excinfo:
        _run(monkeypatch, "sync-emails", "--db", str(db))

    assert excinfo.value.code == 2


def test_db_defaults_to_sonar_db_path(tmp_path, monkeypatch):
    env_db = tmp_path / "env.db"
    monkeypatch.setenv("SONAR_DB_PATH", str(env_db))

    _run(monkeypatch, "allow-email", "owner@example.com")

    assert _stored(env_db) == ["owner@example.com"]


def test_db_flag_wins_over_sonar_db_path(tmp_path, monkeypatch):
    monkeypatch.setenv("SONAR_DB_PATH", str(tmp_path / "env.db"))
    flag_db = tmp_path / "flag.db"

    _run(monkeypatch, "allow-email", "owner@example.com", "--db", str(flag_db))

    assert _stored(flag_db) == ["owner@example.com"]
    assert not (tmp_path / "env.db").exists()
