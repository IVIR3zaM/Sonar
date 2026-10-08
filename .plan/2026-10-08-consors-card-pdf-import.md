# Consors card PDF import
status: DONE
created: 2026-10-08 · updated: 2026-10-08
goal: Consors Finanz Mastercard monthly statement PDFs uploaded on /import land in Sonar as transactions with the card as their source label, deduplicated like the Girokonto CSV; no new account, no balance.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: the owner pays part of the household spending with a Consors Finanz Mastercard, and those purchases, fees, interest and repayments are invisible to Sonar today. Uploading the card's monthly statement PDFs on the existing /import page should store every booking of the statement as a transaction whose source label (the `transactions.account` text) names the card, so categorization, the Monthly page, Keep the lights on and recurring detection see them. No account entity and no balance is added: balance and forecast stay based on the main Girokonto, and the card settlement and CASHCLICK moves are categorized as `transfer` so nothing counts twice.

In scope: one new importer module `src/sonar/importing/importers/consors_finanz_card.py` (NAME, detect, parse; no parse_balance) appended to `IMPORTERS`; pypdf as a pinned dependency; a synthetic PDF test helper and tests for detect, parse, registry pick and the SPEC §4 idempotency cases through the store; a SPEC §13 amendment and the §13 Accounts line.

Out of scope: categorization rules for the card rows (done afterwards through the Categorization workflow, no code); any template, page or UI change (so no visual gate and no CSS rebuild); any account entity or card balance; statement balances; forecast or Monthly logic; other banks; repairing data in `data/sonar.db`.

Constraints: AGENTS.md rules: strict TDD, KISS, pure parsing over plain dataclasses, integer cents, `tests/test_architecture.py` import rules, ruff clean. Real statements live only in `samples/consors/` (gitignored); agents read only a few rows of them and never copy their text, names, IBANs or card numbers into tracked files, tests or commit messages. Decisions D1-D10 below.

Definition of done: the plan `verify` passes; all 8 PDFs in `samples/consors/` imported through `import_file` on a temp DB are each detected as the Consors format with rows added > 0 and an imported sum equal to the statement's section totals minus the dropped UMB rows; importing them again adds 0; one PDF uploaded through POST /import shows the Consors format; SPEC §11/§12 acceptance still holds.

## Decisions

- D1 Detect: the bytes start with `%PDF-` and the extracted text holds "Consors Finanz" and "Kontoauszug zu Consors Finanz Mastercard" | confirmed
- D2 Layout (from `samples/consors/*.pdf`): page 1 is a summary; rows follow headers "Umsätze Ratenzahlung" and "Einmalzahlung vierteljährlich", each with column header "Umsatzdatum Buchungsdatum Verwendungszweck Soll/Haben in EUR"; a row is `[dd.mm.yy] dd.mm.yy TEXT ±1.234,56` with Umsatzdatum optional; ALTER SALDO, NEUER SALDO, GESAMTUMSÄTZE, a bare amount line such as `+433,88`, footnotes, footers and a trailing customer letter (Zinsanpassung) produce no rows | confirmed
- D3 Mapping: source label (the `account` text field) `Consors Mastercard <last 4 digits>` from page 1 "Consors Finanz Mastercard® Nr.: dddd XXXX XXXX dddd"; booking_date = Buchungsdatum; value_date = Umsatzdatum, else Buchungsdatum; two-digit years are 20yy; counterparty = Verwendungszweck; purpose = `Ratenzahlung` or `Einmalzahlung` by section; currency EUR; raw_row = the normalized line; amount in integer cents with its printed sign | confirmed
- D4 Rows starting "UMB. EINMAL- AUF RATENZAHLUNG" (the internal ± pair between the sections) are dropped; interest (MONATLICHE ZINSEN*, ANPASSUNG DER ZINSEN), VERSICHERUNGSPRÄMIE*, CASHCLICK UEBERWEISUNG AUF IHR GIROKONTO and EINGEGANGENE ZAHLUNG are ordinary rows | confirmed
- D5 pypdf pinned exactly (`pypdf==<current release>` via `uv add`), used as `page.extract_text(extraction_mode="layout")` with runs of inner spaces collapsed to one; only the new importer imports it. Statement balances are ignored (no parse_balance). Dedup (SPEC §4) is unchanged | confirmed
- D6 Detect also requires the masked card-number line, and any pypdf error inside detect returns False, so a damaged or foreign PDF gets the existing "Unrecognized file format" message instead of a 500 | confirmed
- D7 Test fixture: a small helper `tests/importing/consors_pdf.py` builds a synthetic PDF in memory (raw PDF objects, Helvetica with WinAnsiEncoding so ä/Ä extract, one page per list of positioned text lines); no binary fixture is committed and no new dev dependency is added | confirmed
- D8 SPEC: add one §13 bullet "Consors card import (§4)" stating D1-D5 in plain words and that it replaces §4's "Later, not now" for this source (§4 text stays as written); rewrite the §13 Accounts line to: no new account is added; Consors card PDFs bring in transactions only, labelled with the card as their source (e.g. `Consors Mastercard 1234`), with no account entity and no balance; balance and forecast stay based on the main Girokonto; card rows count like any other transaction in Monthly, Keep the lights on and recurring detection; the card settlement and CASHCLICK moves are categorized as `transfer` so nothing counts twice | confirmed
- D9 Pre-authorized mid-run: `uv add pypdf==<version>` (network to PyPI, edits `pyproject.toml` and `uv.lock`), and reading `samples/consors/*.pdf` with pypdf in throwaway scripts outside the repo for N02's smoke and N04 | confirmed
- D10 Order: the Consors module is appended after `deutsche_bank_giro` in `IMPORTERS` (`src/sonar/importing/importers/__init__.py:38`); no other registry change | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/haiku | 1 | 0 | DONE | |
| N02 | consors card PDF parser | exec | N01 | opus/sonnet | 1 | 0 | DONE | |
| N03 | register importer and amend SPEC | exec | N02 | sonnet/sonnet | 1 | 0 | DONE | |
| N04 | plan acceptance | check | N03 | -/sonnet | 1 | 0 | DONE | |

## N01 preflight
Do: Confirm the starting point before any work: the untouched tree passes verify, the repo is writable for the per-node commits, PyPI answers for pypdf, and the 8 real statements are present for N02's smoke and N04.
Context: D9: pypdf is fetched into a throwaway environment only (`uv run --with`), so the tree stays untouched. `samples/` is gitignored.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `test -w .git && git rev-parse --abbrev-ref HEAD`
- C3 [cmd] `uv run --with pypdf python -c "import pypdf; print(pypdf.__version__)"`
- C4 [cmd] `test "$(ls samples/consors/*.pdf | wc -l | tr -d ' ')" = 8`
- C5 [cmd] `git diff --exit-code -- pyproject.toml uv.lock`

## N02 consors card PDF parser
Do: Add pypdf as an exact-pinned dependency and a new pure importer module `src/sonar/importing/importers/consors_finanz_card.py` exposing `NAME`, `detect(content: bytes) -> bool` and `parse(content: bytes) -> list[ParsedTransaction]` (no `parse_balance`), with a module docstring recording the confirmed layout as `deutsche_bank_giro.py:1-29` does. Do not register it yet (N03).
Context: D1/D6: detect = `%PDF-` magic, then the text holds "Consors Finanz", "Kontoauszug zu Consors Finanz Mastercard" and the masked card number; any pypdf exception returns False.
  D2: rows only inside the two sections, after the column header; every line not matching the row shape (saldo, totals, bare amount lines, footers, footnotes, letter pages) yields nothing. D4: UMB. EINMAL- AUF RATENZAHLUNG rows are dropped; interest, insurance, CASHCLICK and EINGEGANGENE ZAHLUNG are kept.
  D3: source label `account = "Consors Mastercard <last 4>"` (a text label, no account entity); booking_date = Buchungsdatum, value_date = Umsatzdatum or Buchungsdatum, 20yy years; counterparty = Verwendungszweck; purpose `Ratenzahlung` / `Einmalzahlung`; currency `EUR`; raw_row = the space-collapsed line; cents from `±1.234,56` with integer math, never float.
  D5: `uv add "pypdf==<current release>"`; `extract_text(extraction_mode="layout")`, collapse runs of spaces. Read the real layout from `samples/consors/` with throwaway scripts outside the repo, a few rows at a time (AGENTS.md); nothing from them goes into tracked files.
  D7: `tests/importing/consors_pdf.py` builds a synthetic statement PDF in memory: Helvetica, WinAnsiEncoding (ä/Ä), positioned text lines per page; fake merchant names, card number `0000 XXXX XXXX 1234`.
Read: `src/sonar/importing/importers/deutsche_bank_giro.py`, `src/sonar/transactions.py`, `tests/importing/test_deutsche_bank_giro.py`, `pyproject.toml`
Write: `pyproject.toml`, `uv.lock`, `src/sonar/importing/importers/consors_finanz_card.py`, `tests/importing/consors_pdf.py`, `tests/importing/test_consors_finanz_card.py`
Test first: a synthetic statement with a summary page 1, a Ratenzahlung row with Umsatzdatum and one fee row without it, parses to two transactions with source label `Consors Mastercard 1234`, the expected dates, signed cents and purpose `Ratenzahlung`.
Done when:
- C1 [cmd] `uv run pytest -q tests/importing/test_consors_finanz_card.py`
- C2 [review] Tests cover: detect True on the synthetic PDF; False on the Deutsche Bank fixture `tests/fixtures/db_girokonto.csv`, on a non-PDF, on a PDF without the Consors phrases, on a PDF without the card number and on truncated PDF bytes; `deutsche_bank_giro.detect` False on the synthetic PDF; both sections with their purpose; optional Umsatzdatum; 20yy years; UMB pair dropped; ALTER SALDO, NEUER SALDO, GESAMTUMSÄTZE and a bare `+433,88` line skipped; a trailing letter page yields no rows.
- C3 [review] `pyproject.toml` pins `pypdf==X.Y.Z` exactly; only `consors_finanz_card.py` imports pypdf; parsing is pure with type hints and small named helpers, no float, no `date.today()`; the module has no `parse_balance`; tests and helper hold no real names, IBANs or card numbers.
- C4 [smoke] A throwaway script outside the repo runs `parse` on each `samples/consors/*.pdf`: every file gives rows > 0, one source label, and a cents sum equal to its sections' GESAMTUMSÄTZE minus the dropped UMB rows (printing only file name, row count and the two sums).
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N03 register importer and amend SPEC
Do: Append `consors_finanz_card` to `IMPORTERS` so /import picks it, prove it through the registry and the store with the SPEC §4 idempotency cases, and write the SPEC §13 amendment and Accounts line.
Context: D10: append after `deutsche_bank_giro` at `src/sonar/importing/importers/__init__.py:38`; nothing else in the registry changes. `import_file` (`src/sonar/importing/store.py:31`) already skips `parse_balance` when absent (`:47`) and dedups by `(fingerprint, occurrence)` (`src/sonar/importing/dedup.py:25`); no store change.
  D7: build PDFs with `tests/importing/consors_pdf.py` (from N02); fake data only.
  D8: add one §13 bullet "Consors card import (§4)" after the last bullet in `SPEC.md` (ends at `:255`): Consors Finanz Mastercard monthly statement PDFs are a second import source and replace §4's "Later, not now" for it; rows carry the source label `Consors Mastercard <last 4>`; both sections imported with the section as purpose; the UMB pair dropped; statement balances not imported. Rewrite the Accounts line at `SPEC.md:236` in place: no new account is added; Consors card PDFs bring in transactions only, labelled with the card as their source, with no account entity and no balance; balance and forecast stay based on the main Girokonto; card rows count like any other transaction in Monthly, Keep the lights on and recurring detection; the card settlement and CASHCLICK moves are categorized as `transfer`, so nothing counts twice. Never describe the card as an account (no "second account" or "card account"). Leave §4 text unchanged. No real names or numbers.
Read: `src/sonar/importing/importers/__init__.py`, `tests/importing/test_registry.py`, `tests/importing/test_store.py:1-140`, `tests/importing/consors_pdf.py`, `SPEC.md:36-58`, `SPEC.md:225-255`
Write: `src/sonar/importing/importers/__init__.py`, `tests/importing/test_registry.py`, `tests/importing/test_store_consors.py`, `SPEC.md`
Test first: `pick_importer` on a synthetic Consors PDF returns `consors_finanz_card` with the default `IMPORTERS`, and on the Deutsche Bank fixture still returns `deutsche_bank_giro`.
Done when:
- C1 [cmd] `uv run pytest -q tests/importing`
- C2 [review] `tests/importing/test_store_consors.py` covers, through `import_file` on an in-memory migrated DB: first import adds every row and reports the Consors `NAME` with no balance row stored; the same file twice adds 0; two statements with overlapping rows add only the missing ones; two identical rows in one file are both kept; the same rows in a different order add 0; a stored row keeps source, the card source label in `account`, both dates, purpose and raw_row; no account or balance row is created.
- C3 [review] The registry diff is the one import and the one list entry; the unknown-format error now lists both NAMEs (an existing or new test asserts it); `SPEC.md` diff is the new §13 bullet plus the in-place Accounts line (source label, no new account, no balance, Girokonto-based forecast, settlement and CASHCLICK as `transfer`), §4 untouched, no real names or numbers.
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N04 plan acceptance
Do: Check the whole plan against its Definition of done, SPEC §11 and §12 as amended, and the AGENTS.md rules, including a smoke import of the real statements on a temp DB.
Context: D9: smoke scripts live outside the repo, use a temp DB under `$TMPDIR` (never `data/sonar.db`) and print only file names, counts and sums, never row text.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [smoke] On a fresh temp DB with `apply_migrations`, `import_file` on each of the 8 `samples/consors/*.pdf` reports the Consors format and added > 0, and per file the sum of its stored `amount_cents` equals the statement's section GESAMTUMSÄTZE minus the dropped UMB rows; importing all 8 again adds 0 and reports only duplicates; no row lands in `balances`.
- C3 [smoke] `create_app` on another temp DB under a `TestClient`: POST /import with one Consors PDF and the Deutsche Bank fixture in one upload answers 200 and the results show both format names and no error.
- C4 [review] Per `git diff --stat` since N01: no template, CSS, migration, `/api` route or store change; `pypdf` pinned exactly in `pyproject.toml`; only the importer imports it; `tests/test_architecture.py` passes; SPEC §11 (incl. "a new format needs only one module plus its tests") and §12 hold; fixtures, tests and SPEC hold no real names, IBANs or card numbers.

## Log

### N01 try 1 · 2026-10-08
check: PASS 5/5

### N02 try 1 · 2026-10-08
exec: DONE · 1285 passed
- pypdf==6.19.0 pinned; consors_finanz_card.py importer (unregistered) with layout docstring; synthetic PDF builder tests/importing/consors_pdf.py; 12 tests
- sections end at GESAMTUMSAETZE (July sample lacks NEUER SALDO); section titles matched as exact lines so page-1 summary lines never open a table; detect catches Exception since truncated PDFs raise non-pypdf errors
- C4 smoke: all 8 samples parse, one label each, row sums equal GESAMTUMSAETZE minus UMB rows
check: PASS 2/2
verify: PASS

### N03 try 1 · 2026-10-08
exec: DONE · 1295 passed
- Registered consors_finanz_card after deutsche_bank_giro; registry tests for both pickers and the two-NAME error; store tests in test_store_consors.py
- SPEC §13: new Consors card import bullet and Accounts line rewritten in place; §4 untouched
check: PASS 2/2
verify: PASS

### N04 try 1 · 2026-10-08
check: PASS 1/1
verify: PASS
