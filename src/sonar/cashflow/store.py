"""DB shell for household settings (SPEC §8): salary day, overdraft limit, balance.

Settings live in a single-row table (0005_settings.sql). This module also owns
setting the manual balance override, since both are edited from the same
Settings page and both feed the forecast built in later M5 tasks.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date

from sonar.cashflow.balance import BalanceEntry, latest_balance

# Lives in code, not a column DEFAULT: when no settings row exists yet, a
# column DEFAULT never applies, so this value must be written explicitly on
# every save (see 0005_settings.sql), keeping one source of truth.
DEFAULT_OVERDRAFT_LIMIT_CENTS = -50000

# One household balance overrides any single account's export - there is only
# ever one "current balance" for the dashboard, regardless of which account
# an import came from.
MANUAL_ACCOUNT = "manual"


@dataclass(frozen=True)
class Settings:
    salary_day: int | None
    overdraft_limit_cents: int


def load_settings(conn: sqlite3.Connection) -> Settings:
    """Return the stored settings, or the default overdraft limit unconfigured."""
    row = conn.execute(
        "SELECT salary_day, overdraft_limit_cents FROM settings WHERE id = 1"
    ).fetchone()
    if row is None:
        return Settings(salary_day=None, overdraft_limit_cents=DEFAULT_OVERDRAFT_LIMIT_CENTS)
    salary_day, overdraft_limit_cents = row
    return Settings(salary_day=salary_day, overdraft_limit_cents=overdraft_limit_cents)


def save_settings(conn: sqlite3.Connection, salary_day: int, overdraft_limit_cents: int) -> None:
    """Validate before writing, then upsert the single settings row."""
    if not 1 <= salary_day <= 31:
        raise ValueError(f"salary_day must be between 1 and 31, got {salary_day}")
    if overdraft_limit_cents > 0:
        raise ValueError(f"overdraft_limit_cents must not be positive, got {overdraft_limit_cents}")

    with conn:
        conn.execute(
            """
            INSERT INTO settings (id, salary_day, overdraft_limit_cents)
            VALUES (1, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                salary_day = excluded.salary_day,
                overdraft_limit_cents = excluded.overdraft_limit_cents
            """,
            (salary_day, overdraft_limit_cents),
        )


def set_manual_balance(
    conn: sqlite3.Connection, as_of: date, amount_cents: int, today: date
) -> None:
    """Record a manual balance override, upserting by date (SPEC §4)."""
    if as_of > today:
        raise ValueError(f"as_of {as_of} is in the future (today is {today})")

    with conn:
        conn.execute(
            """
            INSERT INTO balances (account, as_of, amount_cents, source)
            VALUES (?, ?, ?, 'manual')
            ON CONFLICT(account, as_of, source) DO UPDATE SET
                amount_cents = excluded.amount_cents
            """,
            (MANUAL_ACCOUNT, as_of.isoformat(), amount_cents),
        )


def current_balance(conn: sqlite3.Connection) -> BalanceEntry | None:
    """The household's current balance: latest date wins, manual overrides on ties."""
    rows = conn.execute("SELECT as_of, amount_cents, source FROM balances").fetchall()
    entries = [
        BalanceEntry(as_of=date.fromisoformat(as_of), amount_cents=amount_cents, source=source)
        for as_of, amount_cents, source in rows
    ]
    return latest_balance(entries)
