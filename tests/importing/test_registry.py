"""Tests for the importer registry: picking the importer matching a file."""

from types import SimpleNamespace

import pytest

from sonar.importing.importers import UnknownFormatError, pick_importer


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
