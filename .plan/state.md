# Sonar plan state
Milestone: M1 Import | phase: planned, waiting at human checkpoint (user approval + 2 questions)
Replans: 0/2
Last commit: see `git log --oneline -5`; M0 = 13603a5
Plan: `.plan/plan.md` (milestones M1–M5, full M1 task lines, sample layout, open questions)

## Resume (fresh session = orchestrator)
1. Read SPEC.md §1, this file, `.plan/plan.md`; run `git log --oneline -5` and `uv run pytest -q`.
2. If phase says "waiting at human checkpoint": ask the user the open questions in plan.md, then go.
3. Dispatch tasks from plan.md in its order, by subagent_type planner/executor/verifier with the
   model tag from the task line. Pass the task line + file paths, never file contents.
4. After each task: set its status here (todo/done/blocked). After Verifier PASS: commit, mark the
   milestone done, ask the Planner for the next milestone's graph, write it into plan.md.
5. On FAIL: send findings to Planner, replan failing tasks only, bump Replans. Stop after 2.

## Tasks (M1)
- T1 [sonnet] migration 0001_import.sql: todo
- T2 [haiku] anonymized fixture tests/fixtures/db_girokonto.csv: todo
- T3 [sonnet] ParsedTransaction/ParsedBalance + importer registry: todo
- T4 [sonnet] deutsche_bank_giro importer (deps T2,T3): todo
- T5 [opus] fingerprint + occurrence numbering (deps T3): todo
- T6 [opus] import_file + 4 idempotency tests (deps T1,T4,T5): todo
- T7 [sonnet] /import upload page (deps T6): todo
- T8 [haiku] opt-in real-sample test (deps T6): todo
- T9 [haiku] ruff, suite green, CLAUDE.md line (deps T7,T8): todo

## Milestones
- M0 done | M1 planned | M2 | M3 | M4 | M5 (details in plan.md)

## Decisions
- htmx via pinned CDN; migrations named NNNN_*.sql; importer follows real (English-locale) sample

## Open questions
- 2 pending, see plan.md "Open questions" (recommendations included)

## Notes
- pytest warns: starlette httpx deprecation (third-party, harmless)
