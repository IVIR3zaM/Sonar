---
name: plz-new-plan
description: Plan a body of work as a Planzilla task graph under .plan/. Clarifies the request first, picks the tier (S, M or L), agrees the repo config, asks every open decision in as few rounds as possible, then has plz-planner write the plan. Use when the user asks to plan, decompose or build something that needs more than one quick edit, or mentions a plan, task graph or Planzilla. Run it afterwards with plz-run-plan.
argument-hint: <what to build or change, or a path to a request>
---

You set up a plan with the user. You don't explore the codebase; plz-planner does that in its own context.
CLI: run `.planzilla/plz` if that file exists, else `planzilla`; below, `plz <command>` means that program.
Questions go to the user in as few rounds as possible: clarification once (step 1), open decisions once (step 4).

## 1. Clarify first, before any graph (req 6)

1. **Request.** Use the arguments; if empty, ask one line: what should the plan achieve? Keep the request in
   this conversation only: never write it, or a pointer to it, into any file. Only the agreed Intent is stored.
2. **Gaps.** List what the request leaves open: missing parts, hidden assumptions, scope edges, constraints,
   and how "done" will be shown. Read only what you need to see them (README, CLAUDE.md/AGENTS.md).
3. **Tier** (req 5, FORMAT §1): pick the smallest that fits; tiers only escalate later, never back:
   - S: one executor context, no open decisions, 1-2 exec nodes, no preflight and no final check.
   - M: about 2-10 nodes, clear scope.
   - L: more than 10 nodes, several sessions or environments, or evidence files (`runs/`).
4. **Config** (req 8). If `.plan/config.md` is missing, detect values from `pyproject.toml`, `package.json`,
   `Makefile`, `CLAUDE.md`/`AGENTS.md`: `verify` (full check), `verify_fast`, `commit` (`per-node`), `push`
   (`per-node` in a cloud session, else `none`), `retention` (`keep`), `preauthorized`.
5. **One round** (req 7). Ask the gaps, the tier and (when the config is missing) the detected config values together,
   in one AskUserQuestion round (up to 4 questions per call; recommended answer first, labelled
   "(Recommended)"). Ask a follow-up round only if an answer opens a new gap.

## 2. Config

Config missing: write `.plan/config.md` from `templates/config.md` (in `.planzilla/`, else the installed
package's `planzilla/kit/`) with the agreed values; keep every other key at its default.

## 3. Plan

Slug: 2-5 kebab-case words for the outcome. Dispatch `plz-planner` (model: config `models` planner, default
opus) with exactly one line:
`Outline: <slug> · Request: <the agreed intent: goal; in scope; out of scope; constraints; definition of done; tier <T>>`
Pass what was agreed, not the user's raw wording. The planner stores it as the Intent in its own words (L:
`intent.md`; S/M: the `## Intent` section; never the raw prompt) and writes the plan as DRAFT:
- S/M: this one call writes the header (`tier: S` for S), `## Decisions`, `## Graph` and every brief.
- L: `plan.md` and the gate briefs, with the outline; every other brief, check nodes included, comes just in time from plz-run-plan (`Brief:`).
Expect one line `OUTLINED <plan> | tier: <T> | nodes: <n> | open: <k>`.

## 4. Confirm, once

1. Show the user the goal and `plz status <plan>` (at most 25 lines).
2. Collect the open items: `grep -n '| proposed' <plan file>` (L: `plan.md`). They include decisions,
   pre-authorizations (offer "pre-authorize" first, "keep a live gate" second) and verification doubts
   (a criterion only a human can check). Ask them all plus "approve the graph as shown, or change it" in
   one AskUserQuestion round, recommended answer first.
3. Dispatch `Revise: <plan> · D1: <answer> · D3: <answer>[ · graph: <the change>]`. The planner marks the
   lines `confirmed`, applies them to Intent, Graph and briefs, and sets `status: READY` once nothing is
   `proposed`. Expect `REVISED <plan> | open: <k>`; repeat 2-3 only for new `proposed` lines.
   No open items at all: still dispatch `Revise: <plan>` so the planner sets READY.

Never edit the header, Intent, Decisions, Graph or briefs yourself; the planner owns them.

## 5. Finish

1. `plz lint <plan>` must print `lint ok: <n> nodes, <w> waves`; otherwise dispatch
   `Revise: <plan> · lint: <the problem lines>` and run it again.
2. S plan and step 4 had no open items: run it now in this thread, following plz-run-plan.
   Otherwise offer `/plz-run-plan <slug>`; start it only if the user asked for that.
