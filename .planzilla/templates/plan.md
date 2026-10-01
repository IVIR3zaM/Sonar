# <Title in a few words>
status: DRAFT
created: YYYY-MM-DD · updated: YYYY-MM-DD
goal: <one line: the outcome>
verify: <one shell command that must exit 0 for the whole repo; config `verify`>
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node

## Decisions

- D1 <assumption the plan rests on> | confirmed
- D2 <choice with more than one reasonable answer> | proposed · recommend: <answer> · alt: <other answer>
- D3 N03 <action that would stop for a human mid-run> | proposed · recommend: pre-authorize

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/- | 0 | 0 | TODO | |
| N02 | <short title> | exec | N01 | sonnet/sonnet | 0 | 0 | TODO | |
| N03 | <short title> | exec | N01 | opus/opus | 0 | 0 | TODO | |
| N04 | plan acceptance | check | N02,N03 | -/sonnet | 0 | 0 | TODO | |

<!--
Format rules (FORMAT §2-§5; delete this comment in a real plan)
- L layout: this plan.md, intent.md (the Intent), nodes/<id>.md (briefs), log/<id>.md (logs, CLI only),
  runs/<id>/ (evidence). Nothing but the header, Decisions and Graph goes in this file.
- Header: these keys in this order up to the first blank line; status DRAFT until no Decision is `proposed`,
  then READY; the CLI owns status and `updated:` after that. commit/push from config; budgets optional.
- Decisions: `- D<n> <text> | proposed|confirmed[ · recommend: <a>][ · alt: <b>]`, one line each. Every
  assumption, every choice with more than one reasonable answer, every mid-run human stop (pre-authorize it).
- Graph: exactly this header row; cells `| value |`, empty note `| |`. id `N01`, split `N03a`; type exec, check
  or gate; deps `-` or `N01,N02`; model `<exec>/<verify>`: haiku, sonnet, opus or `-`; try 0, rp 0, TODO.
- L: N01 is the preflight check (L3); the last node checks the whole plan, first criterion `verify` (D26).
  Nodes of one wave have disjoint Write paths. A gate node (model -/-) exists only for a Decision kept live for a human.
- Once READY, rows change only through `planzilla set` (D8). Commits come only from `planzilla commit`, one per
  node with its plan state; never a status-only commit (L6).
-->
