# Sonar plan state
Milestone: none | phase: ALL MILESTONES DONE (M5 PASS after 2 replans; SPEC §11 checklist verified)
Replans used: M1 1, M2 0, M3 2, M4 2, M5 2
Plan: `.plan/plan.md` (milestones, task lines per milestone, sample layout). Commits: M0 13603a5, M1 95a052d, M2 a0d0170, M3 a16f99f, M4 28eb946, M5 45f4011

## Resume (fresh session = orchestrator)
1. Read SPEC.md §1, this file, `.plan/plan.md`; run `git log --oneline -5` and `uv run pytest -q`.
2. If phase says "waiting at human checkpoint": ask the user the open questions in plan.md, then go.
3. Dispatch plan.md tasks in order (subagent_type + model tag); pass task line + paths, never contents.
4. After each task set its status here. Verifier PASS: commit, mark done, get next graph into plan.md.
5. On FAIL: send findings to Planner, replan failing tasks only, bump Replans. Stop after 2.

## Tasks
- none; build complete. Next work comes from the user.

## Milestones
- M0–M5 done

## Decisions
- htmx CDN; NNNN_*.sql; English-locale importer; optional parse_balance(); uncategorized = added rows w/o category
- categories.toml MAY use real private names/IBANs (user, 2026-09-23); tests use fake strings only
- Stopped detected series are dropped (vs latest booking date; edited/dismissed kept) (user)
- Loan pays monthly on as-of day from next month (user); installment last = total-(n-1)*rate if >0 else rate
- Forecast window = [balance date+1, payday-1]; future balance dates rejected (user)
- Overdraft limit: default -500.00, editable in Settings; light green worst>=limit, yellow best>=limit, else red (user)
## Open questions
- none; amending M5 graph for overdraft (not a replan)
- Note: verifiers smoke-test with a temp DB, never data/sonar.db; starlette httpx warning is harmless
