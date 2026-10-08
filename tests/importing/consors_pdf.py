"""Builds synthetic Consors Finanz card statement PDFs in memory for the importer tests.

Real statements never go into tests (AGENTS.md); this writes a minimal PDF with
Helvetica in WinAnsiEncoding so umlauts and the ® sign extract like the real ones.
"""

from __future__ import annotations

Line = str | tuple[str, ...]  # a tuple places each part in its own column (at most 4)

_PAGE_TOP, _LINE_HEIGHT = 800, 14
# Date, date, text, amount: the amount column sits far right, as on the real statement.
_COLUMN_X = (40, 110, 180, 470)

CARD_LINE = "Kontoauszug zu Consors Finanz Mastercard® Nr.: 0000 XXXX XXXX 1234"


def statement_pdf(pages: list[list[Line]]) -> bytes:
    """A PDF with one page per list, each line drawn top-down at its own height."""
    font_id = 3
    page_ids = [4 + 2 * index for index in range(len(pages))]
    objects: dict[int, bytes] = {
        1: b"<< /Type /Catalog /Pages 2 0 R >>",
        2: b"<< /Type /Pages /Kids [%s] /Count %d >>"
        % (b" ".join(b"%d 0 R" % page_id for page_id in page_ids), len(pages)),
        font_id: b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica"
        b" /Encoding /WinAnsiEncoding >>",
    }
    for page_id, lines in zip(page_ids, pages, strict=True):
        stream = _content_stream(lines)
        objects[page_id] = (
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842]"
            b" /Resources << /Font << /F1 %d 0 R >> >> /Contents %d 0 R >>" % (font_id, page_id + 1)
        )
        objects[page_id + 1] = b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream)
    return _assemble(objects)


def _content_stream(lines: list[Line]) -> bytes:
    commands = []
    for row, line in enumerate(lines):
        y = _PAGE_TOP - row * _LINE_HEIGHT
        parts = (line,) if isinstance(line, str) else line
        for x, text in zip(_COLUMN_X, parts, strict=False):
            commands.append(b"BT /F1 9 Tf %d %d Td (%s) Tj ET" % (x, y, _pdf_string(text)))
    return b"\n".join(commands)


def _pdf_string(text: str) -> bytes:
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    return escaped.encode("cp1252")


def _assemble(objects: dict[int, bytes]) -> bytes:
    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for object_id in sorted(objects):
        offsets[object_id] = len(out)
        out += b"%d 0 obj\n%s\nendobj\n" % (object_id, objects[object_id])
    xref_offset = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for object_id in sorted(objects):
        out += b"%010d 00000 n \n" % offsets[object_id]
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_offset,
    )
    return bytes(out)
