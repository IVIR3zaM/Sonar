# Sonar plan

Full task graphs from the Planner. `.plan/state.md` tracks status; this file holds the task text
the orchestrator dispatches. On a replan, replace only the failing task lines and note the replan
number under the milestone heading.

## Milestones

- M0 Skeleton | SPEC §10 | DONE 13603a5
- M1 Import: importer registry, Deutsche Bank Girokonto CSV importer, idempotent storage, upload page | SPEC §4, §10
- M2 Categorization: categories.toml taxonomy from sample, rule engine, re-apply on import+startup, Uncategorized page+copy export, CLAUDE.md workflow | SPEC §5 | deps: M1
- M3 Recurring payments: detection (1/2/3/6/12 mo, ±7d, evidence), schedule periods, Fixed payments page edit/pause/resume/dismiss/add, water test | SPEC §6 | deps: M2 (category types), M1 (mandate/creditor)
- M4 Installments and loans: debt model, match rules, paid so far, amortization/linear, link to recurring | SPEC §7 | deps: M1, M3 (link)
- M5 Forecast, dashboard, settings: salary day (weekend→Fri), manual balance latest-wins, traffic light, variable range, fixed-costs 12-month view | SPEC §8, §9, §4 balance | deps: M2–M4

M2–M5 get their task graphs from the Planner when each milestone starts.

## M1 Import (SPEC §2, §3, §4, §10)

Order: {T1, T2, T3} in parallel → {T4, T5} → T6 → {T7, T8} → T9

```
M1 Import
T1 [sonnet] Add migration 0001_import.sql: transactions(source,account,booking_date,value_date,amount_cents,currency,counterparty,purpose,iban,mandate_ref,creditor_id,raw_row,fingerprint,occurrence, UNIQUE(fingerprint,occurrence)) + balances(account,as_of,amount_cents,source import|manual, UNIQUE(account,as_of,source)) | files: src/sonar/migrations/0001_import.sql,tests/test_migration_0001.py | test first: duplicate (fingerprint,occurrence) insert raises IntegrityError; balances accepts manual row | deps: -
T2 [haiku] Create anonymized fixture copying sample structure (read sample lines 1-10 + tail only): BOM, LF, 7 preamble lines, 18-col header, ~8 rows with fake names/IBANs/amounts incl. 2 identical same-day rows, a quoted field containing ';', a Credit "1,234.56", empty mandate/creditor, footer "Account balance;9/23/2026;;;-448.43;EUR" | files: tests/fixtures/db_girokonto.csv | test first: - (consumed by T4) | deps: -
T3 [sonnet] Add ParsedTransaction/ParsedBalance frozen dataclasses (cents, date, optional iban/mandate_ref/creditor_id, raw_row) and registry IMPORTERS list + pick_importer(content: bytes, importers=IMPORTERS) raising UnknownFormatError naming supported formats | files: src/sonar/transactions.py,src/sonar/importers/__init__.py,tests/test_registry.py | test first: stub importers: matching one picked; none matches → error lists names | deps: -
T4 [sonnet] DB Girokonto importer with top-of-module layout comment (see "Confirmed sample layout" below); amount=Debit or Credit; footer "Account balance;<date>;;;<amt>;EUR" → balance; detect = header match; register in IMPORTERS | files: src/sonar/importers/deutsche_bank_giro.py,src/sonar/importers/__init__.py,tests/test_deutsche_bank_giro.py | test first: fixture → exact rows/cents/dates/None fields, quoted ';' intact, balance; detect false on non-DB CSV | deps: T2,T3
T5 [opus] Pure fingerprint(tx) = sha256 of normalized account, booking_date, amount_cents, casefolded+whitespace-collapsed counterparty and purpose; number_occurrences(txs) → (tx, fp, occ 1..k per fp) | files: src/sonar/dedup.py,tests/test_dedup.py | test first: 2 identical rows → occ 1,2; case/space variants share fp; row order does not change the (fp,occ) set | deps: T3
T6 [opus] import_file(conn, content, filename) → ImportResult(format, added, duplicates, uncategorized): pick, parse, number, INSERT OR IGNORE, store balance | files: src/sonar/importing.py,tests/test_importing.py | test first: SPEC §4's 4 tests (same file twice adds 0; overlapping files add only missing rows; identical rows both kept; reordered rows add 0) + balance stored with date | deps: T1,T4,T5
T7 [sonnet] Upload page: GET /import multi-file form; POST /import (HTMX) per-file table format/added/duplicates/uncategorized; clear per-file error listing supported formats; nav link | files: src/sonar/app.py,src/sonar/templates/import.html,src/sonar/templates/base.html,tests/test_import_page.py | test first: posting fixture twice + a junk file shows 0 added on the second and an error naming "Deutsche Bank Girokonto CSV" | deps: T6
T8 [haiku] Opt-in real-sample test: glob samples/*.csv, skip if none; import to tmp DB, assert added>0, balance stored, re-import adds 0; never print/assert on row content | files: tests/test_real_sample.py | test first: skipped when samples/ empty, passes with sample | deps: T6
T9 [haiku] ruff format/fix, full suite green, CLAUDE.md one line "new source = one importer module + fixture tests" | files: CLAUDE.md | test first: - | deps: T7,T8
```

### M1 replan 1 (Verifier FAIL 1: coverage gaps)

Order: {T10, T11, T12} in parallel → T13

```
T10 [haiku] Add three tests for deutsche_bank_giro edge cases; keep the no-header branch in parse | files: tests/test_deutsche_bank_giro.py | test first: (a) detect is False when the fixture bytes contain a Windows-1252 byte that is not valid UTF-8 (e.g. replace one counterparty char with b"\xe4"; the fixture may be pure ASCII, so re-encoding the whole fixture as cp1252 is not enough); (b) parse_balance returns None when the "Account balance" footer line is removed from the fixture bytes; (c) parse(b"not,a,bank,export\n1,2,3,4\n") returns [] | deps: -
T11 [sonnet] Make parse_balance optional in both the Importer Protocol and import_file: remove it from the Protocol in src/sonar/importers/__init__.py (the module docstring already calls it optional) and keep the getattr fallback in importing.py | files: src/sonar/importers/__init__.py,src/sonar/importing.py,tests/test_importing.py | test first: (a) monkeypatch sonar.importing.pick_importer to return a SimpleNamespace stub with NAME, detect and parse (returning the fixture's parsed rows) but no parse_balance; import_file adds the rows and the balances table stays empty; (b) import_file on the fixture with the "Account balance" footer line removed stores 7 transactions and 0 balances rows | deps: -
T12 [haiku] Make the junk-file assertion check junk.csv's own row, not the Format column | files: tests/test_import_page.py | test first: pull out junk.csv's <tr> (the one containing colspan="4") from second.text and assert it contains "Unrecognized file format" and "Supported formats: Deutsche Bank Girokonto CSV" | deps: -
T13 [haiku] Run uv run ruff check ., uv run ruff format --check . and uv run pytest -q; fix any lint or format issues in the touched files only | files: tests/test_deutsche_bank_giro.py,tests/test_importing.py,tests/test_import_page.py,src/sonar/importers/__init__.py,src/sonar/importing.py | test first: full suite green with the new tests from T10–T12 | deps: T10,T11,T12
```

### Confirmed sample layout (samples/Transactions_ACCOUNT_20260923_160058.csv)

Not the German locale SPEC §4 expected; the importer follows the real file.

- UTF-8 with BOM, LF line endings, `;` separator, `"` quoting (20 lines have quoted fields).
- Dates `M/D/YYYY`, unpadded. Amounts English style `-2,167.12` (18 rows have a thousands separator).
- Preamble: L1 `Transactions`; L2 account header; L3 `AktivKonto;<branch/account>;<IBAN>;EUR`; L4 blank;
  L5 `M/D/YYYY - M/D/YYYY`; L6 `Old balance;;;;<amt>;EUR`; L7 pending-transactions note.
- L8 header (18 cols): Booking date;Value date;Transaction Type;Beneficiary / Originator;Payment Details;
  IBAN / Account Number;BIC;Customer Reference;Mandate Reference;Creditor ID;Compensation amount;
  Original Amount;Ultimate creditor;Number of transactions;Number of cheques;Debit;Credit;Currency
- Footer: `Account balance;<date>;;;<amt>;EUR`. ~1303 lines total.
- Credit sign not yet seen in the rows read; assume the Credit column is positive. The fixture covers both.

### Open questions (answered 2026-09-23: both recommendations accepted)

1. Balance source: `parse()` returns only transactions. Recommend: optional importer function
   `parse_balance(file) -> ParsedBalance | None`; store only the closing "Account balance" line.
2. Per-file "uncategorized": recommend this file's rows with no category (all rows until M2).
