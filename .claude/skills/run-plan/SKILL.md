---
name: run-plan
description: Run or resume a Sonar plan from .plan/ as the Orchestrator, dispatching Executor and Verifier subagents node by node. Use when the user asks to run, continue, resume or execute a plan, or to pick up the next piece of work.
argument-hint: [plan name or slug; empty = suggest the next open plan]
---

You are the Orchestrator (CLAUDE.md, Graph workflow). You never write product code, and you keep your context near-empty: you read the plan's head, dispatch agents, route their one-line replies and edit status cells. Never read briefs, Findings, diffs, source files or test output. Never paste an agent's reply to the user.

## 1. Pick the plan

- With an argument: match `.plan/*<arg>*.md`. If there are several matches, ask.
- Without one: run `grep -H '^status:' .plan/20*.md`. Suggest the first plan that is RUNNING, WAITING or BLOCKED, else the oldest READY, else the oldest DRAFT. Confirm it with AskUserQuestion (the suggestion first, up to 3 other open plans). If every plan is DONE, say so and point to `/new-plan`.

## 2. Load the head

Grep `^## Nodes` for its line number and Read the plan up to it. That is the whole state: header, Graph, Open questions. Re-read it only after the Planner has edited the plan.

- **DRAFT:** show the Graph and ask for approval first (the `/new-plan` checkpoint), then continue.
- **Open questions** (`Q` lines): ask each with its recommended answer. Replace the line with `- A1 <answer>`, then dispatch the planner with `Revise: <path> · apply answered questions` and re-read the head.
- **In flight after a stop** (not counted against any budget): RUNNING → dispatch the executor again at the same try (the tree may hold a partial attempt); VERIFYING → dispatch the verifier again; REPLAN → dispatch the planner again; WAITING → ask the user again.
- Set the plan's `status: RUNNING` and `updated:` to today.

## 3. Run waves until every node is DONE

1. **Ready set:** nodes that are TODO or RETRY and whose deps are all DONE. If none are ready: all DONE → step 4; otherwise report the BLOCKED nodes, set plan status BLOCKED, and stop.
2. **Execute:** for each ready `exec` node, set `status RUNNING` and `try +1` in its row, then dispatch all executors of the wave in one message (parallel Agent calls, `subagent_type: executor`, model = the node's exec model):
   `Plan: <path> · Node: N03 · Try: 2`
   On a retry, add: `The tree holds the previous attempt; fix the Findings, don't start over.`
3. **Route executor replies:** `DONE N03 …` → VERIFYING. `BLOCKED N03: <reason>` → note `blocked: <reason>`, go to Replan. A crash or malformed reply → dispatch once more, then stop and tell the user.
4. **Verify** only after every executor of the wave has replied, so no test run sees half-written work. Dispatch the verifiers in one message (`subagent_type: verifier`, model = the node's verify model): `Plan: <path> · Node: N03 · Try: 2`. `check` nodes go straight to this step.
5. **Route verifier replies:**
   - `PASS N03` → set DONE and clear note. Commit that node alone: `git add -A -- <its Write paths that exist> <plan path>`, message `<slug> N03: <title>` plus the attribution lines. One commit per node, in id order.
   - `FAIL N03` + bullets → append the bullets under the node's `Findings:` as `- try K: …`, and set note `fail C2,C4`. A `check` node, a criterion repeated from the previous note, or `try` = 2 → Replan. Otherwise set RETRY.
   - After the wave's commits, `git status --short` must show nothing. Leftovers are edits outside a Write set: stop and tell the user.
6. **Gate nodes:** set WAITING. For a visual check, do it yourself as CLAUDE.md describes; for anything else, ask the user. Pass → DONE and commit the plan. Defects → append them as Findings and go to Replan.
7. **Replan:** if `rp` = 2 → set BLOCKED, tell the user the node and its note in at most 5 lines, and keep running the nodes that don't depend on it. Otherwise set REPLAN, reset the node's uncommitted work (`git restore --staged --worktree -- <Write paths>` and `git clean -fd -- <Write paths>`), and dispatch the planner (`subagent_type: planner`, model opus): `Replan: <path> · Node: N03 · Reason: <note>`. It replies `REPLANNED N03[,N05]` or `SPLIT N03 -> N03a,N03b`, having edited those rows and briefs. Re-read the head.
8. **Report** one line per wave, e.g. `wave 2: N03 ✓ · N04 retry (C2) · next: N05, N06`.

Write every status change into the plan before the dispatch that depends on it. Use Edit on the row; never rewrite the file.

## 4. Finish

When every node is DONE: set `status: DONE` and `updated:`, commit the plan file, and report in at most 5 lines: goal met, number of commits, retries and replans used, and any follow-ups.

## Pausing

The user may interrupt at any time, and a rate or context limit may stop you. The plan file already holds the state. Say `Paused at <node>; /run-plan <slug> resumes.` Never re-read finished work to catch up.

## Human checkpoints

Stop and ask only at: a DRAFT plan, an open question, a gate that needs the user, a BLOCKED node, or a node that needs `samples/` when it is empty.
