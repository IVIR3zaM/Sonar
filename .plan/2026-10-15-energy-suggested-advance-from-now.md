# Energy suggested advance from now on
status: DONE
created: 2026-10-15 · updated: 2026-10-15
goal: The Energy suggested advance is what to pay per advance from now on so that the settlement is about one more advance.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: Today the suggested advance spreads the whole period's projected cost over all of its advances, which ignores what is already paid and how many advances are left. It should instead tell the owner what to pay per advance from now on: the projected shortfall split over the remaining advances plus the settlement itself, so the settlement ends up about one advance.

In scope: the pure status computation in src/sonar/energy/settlement.py and its tests; the SPEC §13 "Energy billing cycle" bullet's suggested-advance sentence (§13 stays the override); the /energy card hint; the dashboard Energy card, `GET /api/energy` and `GET /api/dashboard` carrying the new figure through the existing fields; existing tests moved to the new rule.

Out of scope: the worst case, projected settlement, paid window, advance count and chart rules; the dashboard card's layout; any new page or endpoint.

Constraints: AGENTS.md rules: strict TDD, money in integer cents, exact fractions until the one rounding, domain code takes `today` as a parameter, page tests on ids and text through `tests/html.py`, ruff check and format clean. No CSS class changes, so `sonar.css` is not rebuilt; tier S as the owner chose, so no visual gate.

Definition of done: verify passes; tests pin the prod example ((2457.38 − 1505.00) ÷ 4 → 239 €), the 0 clamp and the zero-remaining-advances case (divisor 1); the /energy hint reads "per advance for the next N advances, about the same at settlement on <date>"; SPEC states the new rule.

## Decisions

- D1 Rule: suggested advance = (the whole period's projected cost, exact fraction − paid so far) ÷ (remaining advance count + 1), rounded up to whole euros; 0 when paid so far ≥ projected cost; none only when there is no projection. /energy hint: "per advance for the next N advance(s), about the same at settlement on <settlement date>" | confirmed
- D2 N, the remaining advance count, is the count behind remaining advances (`due_count`, src/sonar/energy/settlement.py:219-222), kept as a new `MeterStatus.remaining_advance_count: int`, so `GET /api/energy` status gains that key | confirmed
- D3 Hint when N = 0: "no advance left, about this at settlement on <date>" | confirmed
- D4 The dashboard Energy card keeps its "per month" suffix after the figure (src/sonar/web/templates/index.html:315) | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | suggested advance from now on | exec | - | sonnet/sonnet | 1 | 0 | DONE | |

## N01 suggested advance from now on
Do: Change the suggested advance to what to pay per advance from now on, keep the remaining advance count on the
status, move the /energy hint and the SPEC sentence to the new rule, and update every existing test to it.
Context: D1 rule: (projected cost as the exact Fraction − paid_cents) ÷ (N + 1), rounded up to whole euros (100 ct),
  clamped at 0 when paid ≥ projected; None only without a projection (settlement.py:225-238 path). D2 N = `due_count`
  (settlement.py:219-222), new field `remaining_advance_count: int` right after `advance_count` in MeterStatus
  (settlement.py:46-58); both constructors (settlement.py:226, :246) set it. Replace `_suggested_advance`
  (settlement.py:439-441) with a public pure `suggested_advance(projected_cost: Fraction, paid_cents: int,
  remaining_advances: int) -> int` and call it at settlement.py:257. D3 hint at N = 0: "no advance left, about this at
  settlement on <date>". Hint (energy.html:61-62) otherwise: "per advance for the next N advance" / "advances", ", about
  the same at settlement on " + `date(m.current.settlement_date)` without an id (the id `-settlement-date` is taken on
  energy.html:59). The `else` branch at energy.html:63-64 is unreachable (no projection means no cost so far) but stays
  harmless; leave it. D4 dashboard index.html:315 unchanged; it and `/api/dashboard` read the figure through
  `SettlementSummary` (service.py:81-108); fix the comment at service.py:88 to "None without a projection".
  SPEC.md:262: replace the sentence "Suggested advance = the whole period's projected cost ÷ the advance count, rounded
  up to whole euros; none only when there is no projection." with the D1 rule, N's definition (the remaining advances'
  count above) and the hint wording incl. D3.
Read: `src/sonar/energy/settlement.py`, `src/sonar/energy/service.py`, `src/sonar/web/templates/energy.html`,
  `tests/energy/test_settlement.py`, `tests/web/test_energy_page.py`, `tests/html.py`, `SPEC.md`
Write: `src/sonar/energy/settlement.py`, `src/sonar/energy/service.py`, `src/sonar/web/templates/energy.html`,
  `tests/energy/**`, `tests/web/**`, `SPEC.md`
Test first: in tests/energy/test_settlement.py, `suggested_advance(Fraction(245_738), 150_500, 3) == 23_900` (prod
  2026-10-15), a paid ≥ projected case gives 0, and a meter_status on the settlement day with no advance left uses
  divisor 1 (e.g. the test at test_settlement.py:230 becomes 6100 − 5000 = 1100); then the page hint test.
Done when:
- C1 [cmd] `uv run pytest -q tests/energy/test_settlement.py -k suggested` passes with tests for the prod example
  (23 900), the 0 clamp and the zero-remaining-advances divisor 1
- C2 [review] settlement.py computes the figure only in `suggested_advance` from the exact Fraction, rounds once
  (ceil to 100 ct), clamps at 0, and MeterStatus carries `remaining_advance_count` equal to the count behind
  remaining_advances_cents; no float anywhere
- C3 [cmd] `uv run pytest -q tests/web/test_energy_page.py -k suggested` passes with tests asserting the hint text
  for N ≥ 2 ("advances" and the settlement date), N = 1 ("next 1 advance,") and N = 0 (D3 wording)
- C4 [review] every old-rule expectation is moved to the new rule (test_settlement.py:178, :227, :235, :503-508,
  test_energy_page.py:213-214, :290-295, tests/web dashboard and API tests); no test asserts the old ÷ advance count
- C5 [review] SPEC.md:262 states the D1 rule, N and the hint wording; the old sentence is gone; no other SPEC line
  changes; `git diff --stat` shows no change to sonar.css or index.html
- C6 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## Log

### N01 try 1 · 2026-10-15
exec: DONE · 1794 passed
- suggested_advance(projected, paid, remaining) = ceil((projected-paid)/(N+1)) to 100 ct, clamped 0; MeterStatus.remaining_advance_count; /energy hint and SPEC.md:262 moved to the new rule
- tests moved to the new rule; hint tests for N>=2, 1 and 0
check: PASS 3/3
verify: PASS
