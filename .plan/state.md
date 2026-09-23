# Sonar plan state
Milestone: M1 Import (planned, awaiting human checkpoint approval)
Replans: 0/2
## Milestones
- M0 Skeleton: DONE 13603a5
- M1 Import §4 | M2 Categorization §5 | M3 Recurring §6 | M4 Debts §7 | M5 Forecast/dashboard/settings §8,§9
## Tasks (M1) - full lines in Planner output; parallel: {T1,T2,T3} -> {T4,T5} -> T6 -> {T7,T8} -> T9
- T1 [sonnet] migration 0001_import.sql transactions+balances: todo
- T2 [haiku] anonymized fixture tests/fixtures/db_girokonto.csv: todo
- T3 [sonnet] ParsedTransaction/ParsedBalance + importer registry: todo
- T4 [sonnet] deutsche_bank_giro importer (deps T2,T3): todo
- T5 [opus] fingerprint + occurrence numbering src/sonar/dedup.py (deps T3): todo
- T6 [opus] import_file + 4 idempotency tests (deps T1,T4,T5): todo
- T7 [sonnet] /import upload page, multi-file, error (deps T6): todo
- T8 [haiku] opt-in real-sample test, skipped if samples/ empty (deps T6): todo
- T9 [haiku] ruff, suite green, CLAUDE.md line (deps T7,T8): todo
## Confirmed sample layout (not German locale)
- UTF-8 BOM, LF, ';' + '"' quoting, M/D/YYYY unpadded, English amounts "-2,167.12"
- 7 preamble lines, 18-col header, Debit/Credit columns, footer "Account balance;<date>;;;<amt>;EUR"
## Decisions
- htmx via pinned CDN; migrations named NNNN_*.sql
## Open questions (recommendations pending approval)
- balance: optional parse_balance(file); store closing "Account balance" only
- per-file uncategorized = this file's rows with no category (all rows until M2)
## Notes
- .claude/agents/* load at session start; this session used general-purpose agents following them
- pytest warns: starlette httpx deprecation (third-party, harmless)
