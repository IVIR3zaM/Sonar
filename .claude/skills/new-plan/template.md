# <Title in a few words>
status: DRAFT
created: YYYY-MM-DD · updated: YYYY-MM-DD
goal: <one line: the outcome>
request: <one line, or the path of the source text>
spec: SPEC §n, §m
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
budgets: 2 tries per brief · 2 replans per node

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | <short title> | exec | - | sonnet/haiku | 0 | 0 | TODO | |
| N02 | <short title> | exec | N01 | opus/opus | 0 | 0 | TODO | |
| N03 | visual check | gate | N02 | - | 0 | 0 | TODO | |
| N04 | plan acceptance | check | N01,N02,N03 | -/sonnet | 0 | 0 | TODO | |

## Open questions

- none

## Nodes

### N01 <short title>
Do: <2–4 sentences: what changes and why. No backstory.>
Spec: <SPEC §n, or file:line>
Read: <paths the executor needs>
Write: <paths or globs; disjoint from every node it may run in parallel with>
Test first: <the failing test's behavior>
Done when:
- C1 <falsifiable statement>
- C2 the verify command exits 0
Findings:
- none

### N03 visual check
Do: <gate: what the orchestrator or the user checks, and where>
Done when:
- C1 <observable result>
Findings:
- none

### N04 plan acceptance
Do: check the whole plan against its goal.
Done when:
- C1 the verify command exits 0
- C2 SPEC §11 still holds for the areas this plan touched
- C3 <plan-level outcome>
Findings:
- none

<!--
Format rules
- Types: exec (executor, then verifier) · check (verifier only) · gate (orchestrator or user, e.g. visual check or approval).
- model: `exec/verify`; `-` where that phase doesn't exist.
- Node status: TODO · RUNNING · VERIFYING · RETRY · REPLAN · WAITING · DONE · BLOCKED.
- Plan status: DRAFT (awaiting approval) · READY · RUNNING · WAITING (question for the user) · BLOCKED · DONE.
- try: attempts of the current brief. rp: replans used. note: `fail C2,C4`, `blocked: <reason>`, or empty.
- Open questions: `- Q1 <question> | recommend: <answer>`; answered: `- A1 <answer>`.
- Findings: the orchestrator appends `- try K: C2 path:line - problem - expected`.
- Nothing after the last node: agents read a brief from `### N03` to the next `### `.
- Don't copy this comment into a plan.
-->
