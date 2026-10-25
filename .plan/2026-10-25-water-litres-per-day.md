# Water litres per day
status: DONE
created: 2026-10-25 · updated: 2026-10-25
goal: a water meter's Readings table shows litres per day instead of whole m³ per day
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: On a utility meter page, the per-day column of the Readings table becomes useful for water: a household uses a few hundred litres a day, so whole m³ per day rounds to 0 or 1. Water shows whole litres per day under the header "L per day"; gas and electricity keep whole kWh per day exactly as today.

In scope: the per-day figure and its unit in `src/sonar/web/pages/utilities.py` (`USAGE_UNITS`/`ReadingRow`/`MeterCard` at :75-97, `_reading_rows` at :314-341, the card build at :376), the Readings header and per-day cell in `src/sonar/web/templates/utility_meter.html:110,123`, the page tests in `tests/web/test_utility_meter_page.py`, and a one-sentence note in SPEC §13 Utilities, since SPEC §13 Energy (`SPEC.md:261`) lists the column as "kWh per day".

Out of scope: chart units, expected usage per year, period forms, cost math, the garden meter table (it has no per-day column), and when a per-day value shows at all (still only when every day of the interval lies in a billing period).

Constraints: strict TDD (the failing water test comes first); integer and Fraction math only (litres = m³ × 1000, the milli scale readings already use); `USAGE_UNITS` stays as is because the chart and expected usage use it; ruff clean; `sonar.css` is rebuilt and committed only if template classes change (pre-authorized).

Definition of done: verify passes, and a water meter page shows a "L per day" header with whole-litre values such as 312, while gas and electricity pages still show "kWh per day" with the same numbers as before.

## Decisions

- D1 Rounding: litres per day = round_half_up(mean m³ per day × 1000), using the existing `round_half_up` (`src/sonar/utilities/settlement.py:82`) | confirmed
- D2 SPEC: add one sentence to the §13 Utilities bullet saying the Readings per-day column shows whole litres per day for water (the request allows a one-line note) | confirmed
- D3 The per-day hook and field: rename `data-field="kwh_per_day"` and `ReadingRow.kwh_per_day` to `per_day`, since the value is no longer always kWh, and update the tests that read it | confirmed
- D4 Visual check: AGENTS.md asks for a `gate` node after template changes; this plan only swaps the header's unit variable and the cell's hook, with no class or layout change, and page tests assert the header; no gate, keep tier S | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | water per day in litres | exec | - | codex@medium/sonnet | 1 | 0 | DONE | |

## N01 water per day in litres
Do: Make the Readings per-day column of a water meter show whole litres per day under the header "L per day"; gas and electricity keep whole kWh per day unchanged.
  Add `PER_DAY_UNITS = {"gas": "kWh", "electricity": "kWh", "water": "L"}` beside `USAGE_UNITS` (utilities.py:76, which stays), a `per_day_unit` field on `MeterCard` set at utilities.py:376, and use it in the header at utility_meter.html:110.
  In `_reading_rows` (utilities.py:314-341) multiply the water mean per-day Fraction by 1000 before `round_half_up`; rename `ReadingRow.kwh_per_day` (:84) and the cell hook `data-field="kwh_per_day"` (utility_meter.html:123) to `per_day`, updating the tests at test_utility_meter_page.py:161,179.
  Change the water header assertion in the test at test_utility_meter_page.py:923 to "L per day", and add one sentence to the SPEC §13 Utilities bullet (SPEC.md:263) that the Readings per-day column shows whole litres per day for water.
Context: D1 litres per day = round_half_up(mean m³ per day × 1000) with `round_half_up` (src/sonar/utilities/settlement.py:82), Fraction/int math only, no float. D2 one SPEC sentence only. D3 rename the hook and field to `per_day`. D4 no visual gate; no template class changes, so no `sonar.css` rebuild. Water per-day still shows only when every day of the interval is in a billing period (`daily_kwh`, settlement.py:108-115; factor 1 for water at :440-444). Chart, expected usage, period forms and cost math stay untouched.
Read: `src/sonar/web/pages/utilities.py`, `src/sonar/web/templates/utility_meter.html`, `tests/web/test_utility_meter_page.py`, `src/sonar/utilities/settlement.py`, `SPEC.md`
Write: `src/sonar/web/pages/utilities.py`, `src/sonar/web/templates/utility_meter.html`, `tests/web/test_utility_meter_page.py`, `SPEC.md`
Test first: a water meter (`_water_meter`, test file :107) with `_water_period()` (:729, covers 2026) and readings 1_000 on 2026-01-01 and 4_125 on 2026-01-11 shows "313" in the newest row's `[data-field="per_day"]` (3.125 m³ over 10 days = 312.5 L, rounded half up) and "L per day" in the Readings thead; it fails before the code change.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_utility_meter_page.py`
- C2 [cmd] `sh -c '! grep -rn "kwh_per_day" src/sonar/web tests/web'`
- C3 [cmd] `git diff --quiet -- src/sonar/web/static/sonar.css`
- C4 [review] the water test exists and asserts "313" and "L per day"; gas and electricity still show "kWh per day" with the values the tests at :144-180 expect; `USAGE_UNITS`, the chart, expected usage and cost code are unchanged; per-day math is Fraction × 1000 then `round_half_up`, no float; SPEC.md gains exactly one sentence in the §13 Utilities bullet
- C5 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## Log

### N01 try 1 · 2026-10-25
exec: DONE · 2066 passed; ruff check and format clean
- Water Readings show whole litres per day with half-up rounding; per_day field and hook; one SPEC sentence.
- Regression test failed before implementation and passes with 313 L per day; gas and electricity retain kWh values.
check: PASS 4/4
verify: PASS
