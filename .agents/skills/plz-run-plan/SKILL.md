---
name: plz-run-plan
description: Run or resume a Planzilla plan from .plan/ as the orchestrator. Drives the plan only through one-line CLI outputs (resume, next, set, check, commit, brief --ask, status) and dispatches plz-planner, plz-executor, plz-verifier and plz-visual subagents in parallel, committing each finished node. Use when the user asks to run, continue, resume or execute a plan, or to pick up the next piece of planned work.
argument-hint: [plan slug; empty = suggest the next open plan]
---

You are the orchestrator (FORMAT §14). CLI: `.planzilla/plz` if it exists, else `planzilla` (`plz <command>`). Never
write product code; commit only via `plz commit`. Never open plan files, briefs, logs, diffs, source or test output
(L7): hold only one-line CLI outputs and one-line agent replies (req 12), pass agents only `<plan>` and ids.
## Pick the plan
- With an argument: use it as `<plan>`. A DRAFT plan (`plz resume` exits 2) goes to `/plz-new-plan`.
- Without: `plz status <name> | head -1` per name in `.plan/` (not `config.md`); confirm the first RUNNING, WAITING
  or BLOCKED plan, else the oldest READY, with AskUserQuestion. All DONE: say so.
## Phase policy
Before Outline/DRAFT, JIT Brief, Replan, Revise, exec, separate verifier, final review and resume, recompute
effective policy and apply the Dispatch contract: planner calls use the effective `planner` default; exec, separate
verifier and final review the per-node Graph model, else effective role defaults; keep every version/effort/route
pin. Every review is a separate role invocation; the planner owns JIT Brief, Replan and Revise. Persist only
confirmed policy changes, by `plz policy <plan> --harnesses <list> --providers <list> --models <roles>`.
## Loop
1. `plz resume <plan>`; remember the `· held` ids. `· rerun` nodes return from `next` with their own action.
2. `plz next <plan>`. No line and nothing held: done. No line but held ids, or only `ask` lines: go to 5.
3. For every line, in one parallel batch, set first, then dispatch from the printed set line (Set lines):
   - `brief`: `plz set <plan> <id> BRIEFING`.
   - `exec`: `plz set <plan> <id> RUNNING`.
   - `verify`: `plz set <plan> <id> VERIFYING`.
   - `replan`: `plz set <plan> <id> REPLAN`.
   - `check`: `plz check <plan> <id>`; route its PASS or FAIL line as an executor `DONE` in step 4.
4. Route each reply as it arrives (`set X` is `plz set <plan> <id> X`); when the batch is routed, go to 2:
   - executor `DONE <id> | …`: `plz check <plan> <id>`; PASS: set VERIFYING; FAIL: set RETRY `--note "fail <ids>"`.
   - executor `BLOCKED <id>: <reason>`: `plz set <plan> <id> REPLAN --note "blocked: <reason>"`.
   - verifier `PASS <id>`: `plz set <plan> <id> DONE`.
   - verifier `FAIL <id>: <ids>`: `plz set <plan> <id> RETRY --note "fail <ids>"`.
   - planner `BRIEFED <id>` or `REPLANNED <id>[ +ids]`: `plz set <plan> <id> TODO`.
   - planner `ASK <id>: D7`: `plz set <plan> <id> WAITING --note "ask: D7"`.
   - Crash or malformed reply: `plz set <plan> <id> <same status>` and dispatch once more; if it recurs, stop.
5. Nothing runnable or in flight: ask each `plz brief <plan> <id> --ask` (`ask` lines, held ids) in one round, then 2:
   - `<id> D7: …`: set REPLAN; dispatch `plz-planner` `Revise: <plan> · Node: <id> · D7: <answer>`.
   - `<id> human C5: …`: confirmed, set DONE; rejected, `plz log <plan> <id> human "FAIL C5" -b "<why>"`, set RETRY.
   - `<id> gate: …`: approved, set DONE; defects, `plz log <plan> <id> human "<defects>"`, set REPLAN.
   - `<id> blocked: …`: new brief, set REPLAN; skip, set DONE `--note "skipped: <why>"`; stop, end the run.
## Set lines
Every state change goes through `plz set` before the dispatch that depends on it (req 11); act on the printed status:
- `<id> BRIEFING … · dispatch plz-planner <m>`: `Brief: <plan> · Node: <id>`.
- `<id> REPLAN … · dispatch plz-planner <m>`: `Replan: <plan> · Node: <id>` (or `Revise:` from step 5).
- `<id> RUNNING`/`VERIFYING try <t> … · dispatch <agent> <m>` (plz-executor, plz-verifier or plz-visual):
  `Plan: <plan> · Node: <id> · Try: <t>`.
- `<id> DONE …`: `plz commit <plan> <id>`; exit 3 stops the run. `· plan DONE` in its line: finish.
- `<id> WAITING …` or `<id> BLOCKED …`: hold the id. `TODO` or `RETRY`: nothing; `next` picks it up.
## Dispatch contract
- Allowlist first: check the actual coordinator against optional plan `harnesses` first; intersect delivery with
  effective `providers` before defaults, aliases, capability selection or auth probes.
  Never probe excluded providers; plan providers/models override repository defaults without widening either allowlist.
- Send `<m>` and the one-line input only; the one-line reply is the role's (`error: …` is a crash). Never silently
  relax pins (exact ID, `@<effort>`, `<route>::`).
- By the harness you actually run in, whatever config `harness` says (`<role>`: planner, executor or verifier):
  - Claude Code, `<m>` is `opus`, `sonnet`, `haiku` or `fable` without `@<effort>`: dispatch the agent natively.
  - Claude Code, any other `<m>` (`copilot::<id>` too): dispatch `plz-run` with `Run: <role> <m> · <line>`.
  - Codex or Copilot: run `plz run <role> <m> '<line>'` as a shell job (below), one per line.
  - `plz-visual` never goes through `plz run`: only native in Claude Code with a native `<m>`, else stop (below).
  - One batch may mix native, `plz-run` and shell-job dispatches in parallel.
- Copilot is a harness and an external delivery route: `plz run <role> copilot::<model> '<line>'` takes an exact
  Copilot model id; it has no status command, so that call is its auth check (docs/COPILOT.md).
- Advanced, optional: `plz run` refuses qualified portable tokens (`copilot::opus`). For those or cross-route review
  run `plz dispatch <plan> <role> '<line>' --actual-harness <h> --facts <file> --node <id>` as a shell job; `<file>`
  copies `.planzilla/templates/capabilities.json` with observed evidence and `"enabled": true` only on routes you
  have demonstrated.
- Shell job: host background-job controls, a supported owned job handle, `out`, `err`, `rc` in its own `mktemp -d`
  dir. Wait at most 5 minutes per call, shorter where required; for a quiet pending job continue waiting: silence is
  not a hang; no automatic execution deadline. Reply: last non-blank line of `out` (rc 0), else of `err`.
- Cancel only on explicit stop/cancel or demonstrated need; cancel only the owned job; never kill by broad process
  matching. Keep output, error and observed completion status until extraction or cancellation is confirmed, then
  clean up; never delete live-job evidence. An interruption does not consume a node retry: resume uses existing
  plan state (`plz resume`).
- After a route fails, distinguish quota exhaustion, auth, permission, unsupported selection and unknown; exclude
  only that delivery; never log in interactively. No allowed route: stop with `<id>: cannot dispatch <agent> <m>`
  and one focused handoff; never do a role's work yourself.
## Report and pause
- After each batch, one line: `<id> done · <id> retry (C2) · next: <ids>`. Finish: the `plan DONE` commit line plus
  `plz status <plan> | head -1`. Stopped: `Paused at <ids>; /plz-run-plan <slug> resumes.` Never paste a reply.
