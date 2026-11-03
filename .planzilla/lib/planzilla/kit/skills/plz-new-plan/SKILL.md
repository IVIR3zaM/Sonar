---
name: plz-new-plan
description: Plan a body of work as a Planzilla task graph under .plan/. Clarifies the request first, picks the tier (S, M or L), agrees the repo config, asks every open decision in as few rounds as possible, then has plz-planner write the plan. Use when the user asks to plan, decompose or build something that needs more than one quick edit, or mentions a plan, task graph or Planzilla. Run it afterwards with plz-run-plan.
argument-hint: <what to build or change, or a path to a request>
---

You set up a plan with the user; plz-planner explores the codebase in its own context, not you. CLI: `.planzilla/plz`
if it exists, else `planzilla` (`plz <command>`). Ask the user in as few rounds as possible: steps 1 and 4.
## 1. Clarify first, before any graph (req 6)
1. **Request.** Use the arguments, else ask the goal. Keep the raw wording in this conversation; store only Intent.
2. **Gaps.** List what is open (parts, assumptions, scope edges, constraints, proof of done); read only what you need.
3. **Tier** (FORMAT §1): the smallest that fits; tiers only escalate later, never back:
   - S: one executor context, no open decisions, 1-2 exec nodes, no preflight and no final check.
   - M: about 2-10 nodes, clear scope.
   - L: more than 10 nodes, several sessions or environments, or evidence files (`runs/`).
4. **Config** (FORMAT §8): first apply effective policy and the actual coordinator by the Dispatch contract, then:
   - Missing `.plan/config.md`: detect `verify`, `verify_fast`, `commit` (`per-node`), `push` (`per-node` in a
     cloud session, else `none`), `retention` (`keep`) and `preauthorized` from project metadata and repo rules.
   - Allowed providers only: check CLI login, `claude auth status` (exit 0, `"loggedIn": true`), `codex login status`
     (exit 0). Copilot has no status command; its auth check is the call itself (docs/COPILOT.md): logged out,
     `plz run` reports `error: copilot is not logged in; run copilot login`. Login proves no model or quota.
   - Harness: name the client you actually run in, apart from configured `harness`; a hint is not callable evidence.
5. **One round** (req 7): ask gaps, tier and missing config in one AskUserQuestion round, recommended answer first.
   Recommend only allowed, evidenced providers and the actual harness; show a logged-out provider its login
   command, never log in for the user. Config present: ask only requested policy changes or a mismatch.
## 2. Config
Missing: write `.plan/config.md` from `templates/config.md` (`.planzilla/`, else `planzilla/kit/`) with the agreed
values, `providers` and `harness` included. Present: change only agreed lines; never rewrite it to repair dispatch.
## Phase policy
Before Outline/DRAFT, JIT Brief, Replan, Revise, exec, separate verifier, final review and resume, recompute
effective policy and apply the Dispatch contract: planner calls use the effective `planner` default; exec, separate
verifier and final review the per-node Graph model, else effective role defaults; keep every version/effort/route
pin. Every review is a separate role invocation. The planner owns Intent, Graph model tokens and briefs. Persist
only confirmed policy changes, by `plz policy <plan> --harnesses <list> --providers <list> --models <roles>`.
## 3. Plan
Slug: 2-5 kebab-case words for the outcome. Dispatch `plz-planner` (effective planner model) with exactly one line:
`Outline: <slug> · Request: <agreed intent: goal; in scope; out of scope; constraints; definition of done; tier <T>>`
The planner stores it as the Intent in its own words (L: `intent.md`; S/M: the `## Intent` section) in a DRAFT.
S/M: this call writes the header (`tier: S` for S), Decisions, Graph and every brief. L: `plan.md`, outline and gate
briefs; every other brief, check nodes included, comes just in time via `Brief:` from plz-run-plan. Expect
`OUTLINED <plan> | tier: <T> | nodes: <n> | open: <k>`.
## 4. Confirm, once
1. Show the goal and `plz status <plan>` (at most 25 lines).
2. Ask all `| proposed` items (decisions, pre-authorizations: "pre-authorize" first, "keep a live gate" second, human
   verification doubts) plus "approve the graph as shown, or change it" in one AskUserQuestion round.
3. Dispatch `Revise: <plan> · D1: <answer> · D3: <answer>[ · graph: <the change>]` by Phase policy; the planner
   applies them and sets READY once nothing is proposed. Expect `REVISED <plan> | open: <k>`; repeat 2-3 if new.
4. No open items: still dispatch `Revise: <plan>` so the planner sets READY.
Never edit the header, Intent, Decisions, Graph or briefs yourself; planner-only authorship applies to every route.
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
## 5. Finish
1. `plz lint <plan>` must print `lint ok: …`; else dispatch `Revise: <plan> · lint: <problem lines>`, lint again.
2. S plan with no open items in step 4: run it now, following plz-run-plan. Else offer `/plz-run-plan <slug>`.
