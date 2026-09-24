# Sonar plan state
Milestone: M5 Forecast, dashboard, settings | phase: planning (M4 PASS after 2 replans)
Replans: 0/2 (M5); M1 used 1, M2 0, M3 2, M4 2
Plan: `.plan/plan.md` (milestones, task lines per milestone, sample layout). Commits: M0 13603a5, M1 95a052d, M2 a0d0170, M3 a16f99f, M4 see git log

## Resume (fresh session = orchestrator)
1. Read SPEC.md §1, this file, `.plan/plan.md`; run `git log --oneline -5` and `uv run pytest -q`.
2. If phase says "waiting at human checkpoint": ask the user the open questions in plan.md, then go.
3. Dispatch tasks from plan.md in its order, by subagent_type planner/executor/verifier with the
   model tag from the task line. Pass the task line + file paths, never file contents.
4. After each task: set its status here (todo/done/blocked). After Verifier PASS: commit, mark the
   milestone done, ask the Planner for the next milestone's graph, write it into plan.md.
5. On FAIL: send findings to Planner, replan failing tasks only, bump Replans. Stop after 2.

## Tasks (M5)
- (awaiting Planner graph)

## Milestones
- M0 done | M1 done | M2 done | M3 done | M4 done | M5 planning

## Decisions
- htmx via pinned CDN; NNNN_*.sql migrations; importer follows real (English-locale) sample
- Optional importer parse_balance() stores closing balance; per-file uncategorized = added rows w/o category
- categories.toml MAY use real private names/IBANs (user, 2026-09-23); tests use fake strings only
- Stopped detected series are dropped (vs latest booking date; edited/dismissed kept) (user)
- Loan payments monthly on the as-of date's day from the next month; projection follows it (user)
- Installment last payment = total-(n-1)*rate if >0 else rate (orchestrator, planner rec)

## Open questions: none
- Note: verifiers smoke-test with a temp DB, never data/sonar.db; starlette httpx warning is harmless
