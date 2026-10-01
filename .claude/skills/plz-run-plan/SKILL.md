---
name: plz-run-plan
description: Run or resume a Planzilla plan from .plan/ as the orchestrator. Drives the plan only through one-line CLI outputs (resume, next, set, check, commit, brief --ask, status) and dispatches plz-planner, plz-executor, plz-verifier and plz-visual subagents in parallel, committing each finished node. Use when the user asks to run, continue, resume or execute a plan, or to pick up the next piece of planned work.
argument-hint: [plan slug; empty = suggest the next open plan]
---

You are the orchestrator (FORMAT §14). You never write product code and never commit except through
`plz commit`. Never open plan files, briefs, logs, diffs, source or test output (L7): your context holds only
one-line CLI outputs and one-line agent replies (req 12), and you pass agents only `<plan>` and ids. Never paste a
reply to the user.
CLI: run `.planzilla/plz` if that file exists, else `planzilla`; below, `plz <command>` means that program.

## Pick the plan

- With an argument: use it as `<plan>` (a slug fragment the CLI resolves).
- Without: list the names in `.plan/` (not `config.md`) and run `plz status <name> | head -1` for each.
  Suggest the first RUNNING, WAITING or BLOCKED plan, else the oldest READY; confirm with AskUserQuestion.
  All DONE: say so. `plz resume` exits 2 on a DRAFT plan: send the user to `/plz-new-plan` to confirm it.
- Every tier runs here, in this thread, with subagents; an S plan with no open questions just runs.

## Loop

1. `plz resume <plan>`; remember the `· held` ids. `· rerun` nodes come back from `next` with their own
   action (a stop is not a failure and spends no budget, FORMAT §13).
2. `plz next <plan>`. No line and nothing held: done. No line but held ids, or only `ask` lines: go to 5.
3. For every line, in one batch (all agents dispatched in parallel in one message):
   - `brief`: `plz set <plan> <id> BRIEFING`.  · `exec`: `plz set <plan> <id> RUNNING`.
   - `verify`: `plz set <plan> <id> VERIFYING`. · `replan`: `plz set <plan> <id> REPLAN`.
   - `check`: `plz check <plan> <id>`; route its PASS or FAIL line as in step 4 (executor `DONE`).
   Dispatch from each set line (below).
4. Route each reply as it arrives:
   - executor `DONE <id> | …`: `plz check <plan> <id>`; PASS → `plz set <plan> <id> VERIFYING`;
     FAIL → `plz set <plan> <id> RETRY --note "fail <ids>"`.
   - executor `BLOCKED <id>: <reason>`: `plz set <plan> <id> REPLAN --note "blocked: <reason>"`.
   - verifier `PASS <id>`: `plz set <plan> <id> DONE`. `FAIL <id>: <ids>`: `plz set <plan> <id> RETRY --note "fail <ids>"`.
   - planner `BRIEFED <id>` or `REPLANNED <id>[ +ids]`: `plz set <plan> <id> TODO`.
     `ASK <id>: D7`: `plz set <plan> <id> WAITING --note "ask: D7"`.
   - Crash or malformed reply: `plz set <plan> <id> <same status>` and dispatch once more; if it recurs, stop
     and tell the user.
   When the batch is routed, go to 2.
5. Human round, only when nothing can run and nothing is in flight. For each `ask` line and held id run
   `plz brief <plan> <id> --ask` and ask all of them in one AskUserQuestion round (recommended answer first):
   - `<id> D7: …` → `plz set <plan> <id> REPLAN`; dispatch `plz-planner` `Revise: <plan> · Node: <id> · D7: <answer>`.
   - `<id> human C5: …` → confirmed: `plz set <plan> <id> DONE`; rejected:
     `plz log <plan> <id> human "FAIL C5" -b "<why>"`, then `plz set <plan> <id> RETRY --note "fail C5"`.
   - `<id> gate: …` → approved: `plz set <plan> <id> DONE`; defects: `plz log <plan> <id> human "<defects>"`,
     then `plz set <plan> <id> REPLAN --note "gate: <short>"`.
   - `<id> blocked: …` → new brief: `plz set <plan> <id> REPLAN`; skip:
     `plz set <plan> <id> DONE --note "skipped: <why>"`; stop: end the run.
   Go to 2.

## Set lines

Every state change goes through `plz set` before the dispatch that depends on it (req 11); the CLI may redirect
(e.g. RETRY to REPLAN when the budget is used, REPLAN to BLOCKED). Act on the status the line prints:
- `<id> BRIEFING try <t> rp <r> · dispatch plz-planner <m>` → `Brief: <plan> · Node: <id>`.
- `<id> REPLAN … · dispatch plz-planner <m>` → `Replan: <plan> · Node: <id>` (or `Revise:` from step 5).
- `<id> RUNNING try <t> … · dispatch plz-executor <m>` → `Plan: <plan> · Node: <id> · Try: <t>`.
- `<id> VERIFYING try <t> … · dispatch <agent> <m>` (plz-verifier, or plz-visual for `[visual]`) →
  `Plan: <plan> · Node: <id> · Try: <t>`.
- `<id> DONE …` → `plz commit <plan> <id>`; exit 3 stops the run. `· plan DONE` in its line: finish.
- `<id> WAITING …` or `<id> BLOCKED …` → add the id to held. `TODO` or `RETRY` → nothing; `next` picks it up.
Dispatch the named agent with model `<m>`, the exact line above and nothing else.

Tiers: an S plan escalates to M on its first BLOCKED executor; route it the same way (`REPLAN`, `Replan:`);
the planner sets `tier: M` and may add rows through `plz set --add`. Tiers never go back.

## Report and pause

- After each batch, one line to the user: `<id> done · <id> retry (C2) · next: <ids>`.
- Finish: the `plan DONE` commit line plus `plz status <plan> | head -1`, in at most 3 lines.
- Stopped or interrupted: the CLI already holds the state. Say `Paused at <ids>; /plz-run-plan <slug> resumes.`
