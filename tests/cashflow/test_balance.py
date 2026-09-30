"""Tests for balance entry management."""

from datetime import date

from sonar.cashflow.balance import BalanceEntry, latest_balance


class TestLatestBalance:
    """Test latest_balance function that implements 'latest date wins, manual beats import'."""

    def test_empty(self) -> None:
        """Empty list returns None."""
        assert latest_balance([]) is None

    def test_single_import(self) -> None:
        """Single import entry is returned."""
        entry = BalanceEntry(date(2026, 9, 23), 100000, "import")
        assert latest_balance([entry]) == entry

    def test_single_manual(self) -> None:
        """Single manual entry is returned."""
        entry = BalanceEntry(date(2026, 9, 23), 100000, "manual")
        assert latest_balance([entry]) == entry

    def test_import_after_manual(self) -> None:
        """Import dated after manual wins (latest date wins)."""
        manual = BalanceEntry(date(2026, 9, 20), 50000, "manual")
        import_entry = BalanceEntry(date(2026, 9, 23), 100000, "import")
        assert latest_balance([manual, import_entry]) == import_entry
        assert latest_balance([import_entry, manual]) == import_entry

    def test_manual_after_import(self) -> None:
        """Manual dated after import wins (latest date wins)."""
        import_entry = BalanceEntry(date(2026, 9, 20), 50000, "import")
        manual = BalanceEntry(date(2026, 9, 23), 100000, "manual")
        assert latest_balance([import_entry, manual]) == manual
        assert latest_balance([manual, import_entry]) == manual

    def test_same_date_manual_beats_import(self) -> None:
        """On the same date, manual beats import (explicit override)."""
        import_entry = BalanceEntry(date(2026, 9, 23), 50000, "import")
        manual = BalanceEntry(date(2026, 9, 23), 100000, "manual")
        assert latest_balance([import_entry, manual]) == manual
        assert latest_balance([manual, import_entry]) == manual

    def test_negative_amount_returned_unchanged(self) -> None:
        """Negative amounts are returned unchanged."""
        entry = BalanceEntry(date(2026, 9, 23), -5000, "manual")
        assert latest_balance([entry]) == entry
        assert latest_balance([entry]).amount_cents == -5000

    def test_multiple_entries_chronological_order(self) -> None:
        """With multiple entries, latest date wins, manual beats import on same date."""
        oldest = BalanceEntry(date(2026, 9, 20), 10000, "import")
        middle = BalanceEntry(date(2026, 9, 22), 50000, "manual")
        latest_import = BalanceEntry(date(2026, 9, 23), 100000, "import")
        latest_manual = BalanceEntry(date(2026, 9, 23), 120000, "manual")

        assert latest_balance([oldest, middle, latest_import, latest_manual]) == latest_manual
        assert latest_balance([oldest, middle, latest_import]) == latest_import
        assert latest_balance([oldest, middle, latest_manual]) == latest_manual
