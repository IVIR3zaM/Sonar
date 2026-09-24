# Sonar plan state
Milestone: none | phase: ALL MILESTONES DONE (M0–M6); next: wait for the user
Replans used: M1 1, M2 0, M3 2, M4 2, M5 2, M6 2
Plan: `.plan/plan.md` (milestones, task lines per milestone, sample layout). Commits: M0 13603a5, M1 95a052d, M2 a0d0170, M3 a16f99f, M4 28eb946, M5 45f4011

## Resume (fresh session = orchestrator)
1. Read SPEC.md §1, this file, `.plan/plan.md`; run `git log --oneline -5` and `uv run pytest -q`.
2. If phase says "waiting at human checkpoint": ask the user the open questions in plan.md, then go.
3. Dispatch plan.md tasks in order (subagent_type + model tag); pass task line + paths, never contents.
4. After each task set its status here. Verifier PASS: commit, mark done, get next graph into plan.md.
   M6: before the commit, the orchestrator does the SPEC §12 visual check in the browser pane.
5. On FAIL: send findings to Planner, replan failing tasks only, bump Replans. Stop after 2.

## Tasks
- M6 T1-T25 done; Verifier PASS; §12 visual check PASS (temp DB, desktop+375px, light+dark)

## Milestones
- M0–M6 done

## Decisions
- htmx CDN (M6: vendored); NNNN_*.sql; English-locale importer; optional parse_balance(); uncategorized = added rows w/o category
- categories.toml MAY use real private names/IBANs (user, 2026-09-23); tests use fake strings only
- Stopped detected series are dropped (vs latest booking date; edited/dismissed kept) (user)
- Loan pays monthly on as-of day from next month (user); installment last = total-(n-1)*rate if >0 else rate
- Forecast window = [balance date+1, payday-1]; future balance dates rejected (user)
- Overdraft limit: default -500.00, editable in Settings; light green worst>=limit, yellow best>=limit, else red (user)
- M6 (user, 2026-09-24): Tailwind v4 via pytailwindcss, built CSS committed; eur display filter, money kept for inputs; page tests use hooks; no human checkpoint after the M6 plan (run to done unless the spec is ambiguous)
## Open questions
- none
- Note: verifiers smoke-test with a temp DB, never data/sonar.db; starlette httpx warning is harmless
