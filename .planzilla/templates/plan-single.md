# <Title in a few words>
status: DRAFT
created: YYYY-MM-DD · updated: YYYY-MM-DD
goal: <one line: the outcome>
verify: <one shell command that must exit 0 for the whole repo; config `verify`>
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: <the outcome in one or two sentences, in the planner's words; never the raw request>

In scope: <what this plan changes>

Out of scope: <what it deliberately leaves alone>

Constraints: <rules, budgets, tools, deadlines and confirmed Decisions the work must respect>

Definition of done: <the observable result that ends the plan>

## Decisions

- D1 <assumption the plan rests on> | confirmed
- D2 <choice with more than one reasonable answer> | proposed · recommend: <answer> · alt: <other answer>

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/- | 0 | 0 | TODO | |
| N02 | <short title> | exec | N01 | sonnet/sonnet | 0 | 0 | TODO | |
| N03 | plan acceptance | check | N02 | -/sonnet | 0 | 0 | TODO | |

## N01 preflight
Do: Confirm the starting point before any work: the verify command passes on the untouched tree, and every tool
the plan needs, its auth, each network endpoint and each permission (write and push rights, tools the agents
will run) answers.
Done when:
- C1 [cmd] `<plan verify command>`
- C2 [cmd] `<a command proving a needed tool works and its auth is valid>`
- C3 [cmd] `<a command proving a needed network endpoint is reachable>`
- C4 [cmd] `<a command proving a needed permission, e.g. write or push rights>`

## Log

<!--
Format rules (FORMAT §1-§7; delete this comment in a real plan)
- S/M layout: one file .plan/<date>-<slug>.md with exactly these top-level sections in this order: title and
  header, Intent, Decisions, Graph, one `## <id> <title>` brief per Graph row in row order, Log (last).
- tier: S (one executor context, 1-2 exec nodes, no open decisions; no preflight and no final check) or M
  (about 2-10 nodes; the default). Tiers only escalate: an S node blocked makes it M; more than 10 nodes or
  evidence in runs/ moves it to L.
- Header, Decisions and Graph as in the L plan.md template; Intent as in intent.md; each brief as in node.md
  with the heading `## <id> <title>`. All briefs are written with the plan (S/M), each at most 40 lines (L1).
- M: N01 is the preflight check (L3), the last node a whole-plan check running `verify`; S has neither (D26).
  A check node has no Write.
- Log stays empty here: only the CLI appends to it (`planzilla log`, `check`, `resume`), with headings
  `### <id> <key> · <date>`.
- Once READY, rows change only through `planzilla set`; commits come only from `planzilla commit` (L6).
-->
