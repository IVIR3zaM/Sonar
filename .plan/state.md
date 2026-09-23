# Sonar plan state
Milestone: M2 Categorization | phase: planning (M1 PASS after replan 1)
Replans: 0/2 (M2); M1 used 1
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

## Tasks (M1; replan 1 lines in plan.md "M1 replan 1")
- T1–T9: done (verify 1 FAIL)
- T10 [haiku] giro edge-case tests: done
- T11 [sonnet] parse_balance optional in Protocol + tests: done
- T12 [haiku] page junk-row assertion: done
- T13 [haiku] lint + suite green (deps T10–T12): done

## Milestones
- M0 done | M1 done (commit "M1: import") | M2 | M3 | M4 | M5 (details in plan.md)

## Decisions
- htmx via pinned CDN; migrations named NNNN_*.sql; importer follows real (English-locale) sample
- Balance: optional importer fn parse_balance(content) -> ParsedBalance | None; closing "Account balance" only
- Per-file uncategorized = this file's added rows with no category (all rows until M2)

## Open questions
- none (Q1, Q2 answered 2026-09-23, see Decisions)

## Notes
- Verify 1 FAIL: missing tests (non-UTF-8 detect, no-footer balance, no-header parse, optional parse_balance vs Protocol, page error assertion); smoke-test DB moved out of data/
- pytest warns: starlette httpx deprecation (third-party, harmless)
