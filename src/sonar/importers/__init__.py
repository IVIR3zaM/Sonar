"""Importer registry: pick the module whose `detect` matches an uploaded file.

Each importer is a module exposing `NAME: str`, `detect(content: bytes) ->
bool`, `parse(content: bytes) -> list[ParsedTransaction]`, and optionally
`parse_balance(content: bytes) -> ParsedBalance | None`. Adding a source
means adding one module to `IMPORTERS`, per SPEC §4.
"""

from __future__ import annotations

from typing import Protocol

from sonar.transactions import ParsedTransaction

from . import deutsche_bank_giro


class Importer(Protocol):
    """Required shape of every importer module.

    `parse_balance` is not part of this Protocol: it is optional per-module,
    and `import_file` reaches it with `getattr(importer, "parse_balance",
    None)` instead of requiring it here.
    """

    NAME: str

    def detect(self, content: bytes) -> bool: ...

    def parse(self, content: bytes) -> list[ParsedTransaction]: ...


class UnknownFormatError(Exception):
    """Raised when no registered importer detects a file's format."""


# Add a source by appending its module here; nothing else in this file changes.
IMPORTERS: list[Importer] = [deutsche_bank_giro]


def pick_importer(content: bytes, importers: list[Importer] = IMPORTERS) -> Importer:
    """Return the importer whose `detect` matches `content`.

    Raises `UnknownFormatError` naming the supported formats when none match,
    so the upload page can show the user what it does understand.
    """
    for importer in importers:
        if importer.detect(content):
            return importer

    supported = ", ".join(importer.NAME for importer in importers)
    raise UnknownFormatError(f"Unrecognized file format. Supported formats: {supported}")
