---
name: new-plan
description: Plan a piece of Sonar work as a task graph in a new dated file under .plan/. Use when the user asks to plan, build, add, change or fix anything in this repo that goes through the graph workflow (CLAUDE.md).
argument-hint: <what to build or change, or a path to a request>
---

You set up a plan. You don't explore the codebase yourself: the Planner does that in its own context.

1. **Request.** Use the arguments. If they are empty, ask one line: what should the plan achieve? If the request is long or already in a file, pass its path instead of its text.
2. **Name.** Today's date (`date +%F`) plus a 2–5 word kebab-case slug of the outcome, e.g. `.plan/2026-09-25-consors-pdf-import.md`. If the file exists, add `-2`.
3. **Plan.** Dispatch the `planner` agent (model opus) with exactly:
   `New plan: <path> · Request: <request text or path>`
   Expect one line: `PLANNED <path> | nodes: n | waves: w | Q: k`.
4. **Checkpoint.** Grep `^## Nodes` in the plan for its line number, Read the plan up to that line (the head only), and show the user:
   - the goal and the Graph table (at most 25 lines);
   - each open question with its recommended answer.
5. **Revise** on feedback or answers: dispatch the planner with `Revise: <path> · <feedback or answers, one line each>`, then repeat step 4.
6. **Approve.** On approval set `status: READY` in the plan and offer `/run-plan <slug>`. Start it right away only if the user asked for that.

Never write briefs or edit the Graph yourself in this skill; the Planner owns the plan's content.
