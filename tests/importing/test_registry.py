"""Tests for the importer registry: picking the importer matching a file."""

from pathlib import Path
from types import SimpleNamespace

import pytest

from sonar.importing.importers import (
    UnknownFormatError,
    consors_finanz_card,
    deutsche_bank_giro,
    pick_importer,
)
from tests.importing.consors_pdf import CARD_LINE, statement_pdf

DB_FIXTURE = Path(__file__).parent.parent / "fixtures" / "db_girokonto.csv"


def _importer(name: str, matches: bool) -> SimpleNamespace:
    return SimpleNamespace(NAME=name, detect=lambda content: matches, parse=lambda content: [])


def test_pick_importer_returns_the_one_that_matches() -> None:
    wrong = _importer("Wrong Bank CSV", matches=False)
    right = _importer("Right Bank CSV", matches=True)

    picked = pick_importer(b"some content", importers=[wrong, right])

    assert picked is right


def test_pick_importer_raises_and_lists_supported_formats_when_none_match() -> None:
    a = _importer("Bank A CSV", matches=False)
    b = _importer("Bank B CSV", matches=False)

    with pytest.raises(UnknownFormatError) as excinfo:
        pick_importer(b"some content", importers=[a, b])

    assert "Bank A CSV" in str(excinfo.value)
    assert "Bank B CSV" in str(excinfo.value)


def test_default_registry_picks_the_consors_card_pdf() -> None:
    content = statement_pdf([[CARD_LINE]])

    assert pick_importer(content) is consors_finanz_card


def test_default_registry_still_picks_deutsche_bank_for_its_csv() -> None:
    assert pick_importer(DB_FIXTURE.read_bytes()) is deutsche_bank_giro


def test_default_registry_error_lists_both_supported_formats() -> None:
    with pytest.raises(UnknownFormatError) as excinfo:
        pick_importer(b"not a known format")

    assert deutsche_bank_giro.NAME in str(excinfo.value)
    assert consors_finanz_card.NAME in str(excinfo.value)
