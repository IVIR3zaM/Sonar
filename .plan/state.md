# Sonar plan state
Milestone: M4 Installments and loans | phase: planning (M3 PASS after 2 replans)
Replans: 0/2 (M4); M1 used 1, M2 0, M3 2
Plan: `.plan/plan.md` (milestones, task lines per milestone, sample layout). Commits: M0 13603a5, M1 95a052d, M2 a0d0170, M3 see git log

## Resume (fresh session = orchestrator)
1. Read SPEC.md §1, this file, `.plan/plan.md`; run `git log --oneline -5` and `uv run pytest -q`.
2. If phase says "waiting at human checkpoint": ask the user the open questions in plan.md, then go.
3. Dispatch tasks from plan.md in its order, by subagent_type planner/executor/verifier with the
   model tag from the task line. Pass the task line + file paths, never file contents.
4. After each task: set its status here (todo/done/blocked). After Verifier PASS: commit, mark the
   milestone done, ask the Planner for the next milestone's graph, write it into plan.md.
5. On FAIL: send findings to Planner, replan failing tasks only, bump Replans. Stop after 2.

## Tasks (M4)
- (awaiting Planner graph)

## Milestones
- M0 done | M1 done | M2 done | M3 done | M4 planning | M5

## Decisions
- htmx via pinned CDN; migrations named NNNN_*.sql; importer follows real (English-locale) sample
- Balance: optional importer fn parse_balance(content) -> ParsedBalance | None; closing "Account balance" only
- Per-file uncategorized = this file's added rows with no category (all rows until M2)
- categories.toml MAY use real private names/IBANs (user, 2026-09-23); tests use fake strings only
- Stopped detected series are dropped (vs latest booking date; edited/dismissed kept) (user)

## Open questions: none

## Notes
- Verifiers smoke-test with a temp DB, never data/sonar.db; starlette httpx warning is harmless
