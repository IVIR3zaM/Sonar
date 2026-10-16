# Garden water sub-meters
status: RUNNING
created: 2026-10-16 · updated: 2026-10-16
goal: optional garden water meters whose usage is deducted from the main water meter's wastewater
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: A household with a Gartenwasserzähler pays wastewater only on the water that reaches the sewer. Sonar
should let the owner link one or more garden meters to a main water meter, bill wastewater on the main usage
minus the garden usage (plus an optional yearly garden-meter fee), and keep drinking water on the full usage.
Alongside, a period whose advances follow the supplier's schedule should drive the recurring payment that
pays them, so every forecast and the Fixed payments page show the supplier's dates instead of a guessed cadence.

In scope: a nullable link from a water meter to its main water meter; garden meters with readings, exchanges
and a chart but no periods; per-day net wastewater m³ with the gardens summed; each meter projected from its
own history; an optional net yearly garden fee on the main period with wastewater VAT; detection of intervals
where garden usage beats main usage with three owner choices (zero it out, reject the reading, record it as
an exchange); the Utilities water card, garden meter page, forms, API and the SPEC §13 Utilities bullet.
The advance link (D16): a schedule-mode period in force sets the due dates and amount of its category's
recurring payment in the dashboard due list, the payday forecast, Fixed costs, Payoff and Fixed payments; the
supplier's dates apply from the period's start through its settlement or last advance, the payment's own
cadence outside; links are derived on each load and pair one-to-one in id order; the link shows on the Fixed
payments row, the utilities card and meter page, `/api/recurring`, `/api/utilities` and a new SPEC §13 bullet.

Out of scope: one-off registration fees, the 6-year calibration reminder, minimum-deduction thresholds
(Bagatellgrenze), garden meters for gas or electricity, loading any real data; a hand-set or stored
advance link; any link for flexible periods or for recurring payments of another category.

Constraints: a water meter without garden meters keeps every figure it has today (the D6/D7 pins of the
utilities-water-meters plan stay green, untouched); gas and electricity unchanged; append-only migration
0017 keeps every hand-entered utility row; strict TDD; pure functions with `today` a parameter; exact
Fraction math rounded half up once per shown figure; integer cents; page tests on ids and data-*; sonar.css
rebuilt; test_architecture green; the scheduled-advance tests at tests/cashflow/test_service.py:1020-1054
change only as D16 requires; each advance is forecast once; the Decisions below once confirmed.

Definition of done: verify passes; a water meter with one or two garden meters shows the deducted wastewater
cost and the optional fee on /utilities and in the dashboard settlement; a meter without garden meters shows
unchanged figures; a conflict offers the three choices; a recurring payment linked to a schedule period is
due on the supplier's dates on the dashboard and on Fixed payments, with the link shown on both sides, and a
schedule period without one still adds "<meter> advance"; the visual gate passes at desktop and 375px, light
and dark; the final check passes SPEC §11 and §12.

## Decisions

- D1 A garden meter is a `water` meter with `main_meter_id` set; the main must exist, be `water` and not be a garden meter itself (no chains); a main may have several | confirmed
- D2 The link is set when the meter is created (add-meter form, API POST) and never changed; a wrong link is fixed by deleting the empty meter and adding it again | confirmed
- D3 A garden meter has readings, exchanges and a chart but never a billing period (store refuses one, field `meter`), so it has no status, settlement or forecast item; deleting a meter that garden meters link to is refused like a non-empty meter | confirmed
- D4 Per day: wastewater m³ = max(0, main m³ − summed garden m³); drinking water stays on the full main m³; with no garden meter every figure is exactly today's | confirmed
- D5 Garden m³ per day: measured where its readings cover the day; after its last point, inside each main period, the seasonal rule on its own history with expected usage 0 (no history: 0); before its first point 0 | confirmed
- D6 Worst case: wastewater per day = max(0, main worst-case m³ − summed garden m³ of D5); the garden gets no worst case of its own | confirmed
- D7 Garden fee: one optional `garden_fee_cents` per main water period, the net yearly fee for all its garden meters together as on the bill; water only, >= 0, empty (null) = no fee; billed by the base-fee months rule on days with usage, with wastewater VAT; shown as a third charge `garden_fee`, absent when null; "Start new period" copies it | confirmed
- D8 Conflict: on days where the main and a garden both have measured usage, a day conflicts when the summed measured garden m³ exceeds the main m³; a case is one garden meter's interval between two consecutive points of its continuous series that holds a conflicting day on which it used water; excess = sum over those days of (garden sum − main), m³ thousandths, rounded half up once; figures always use the D4 clamp, a case only asks the owner | confirmed
- D9 Choices per open case: Zero it out stores (garden meter, interval start, interval end) in a new table and the case stops alerting (a changed interval asks again); Reject the reading deletes the point that closes the interval (reading or exchange); Record as exchange (closing point is a reading only) replaces that reading, in one transaction, by an exchange on its date with new start = the reading's value and old final entered by the owner; saving a reading never blocks, the case appears afterwards | confirmed
- D10 UI: /utilities shows no card for a garden meter; the main water card lists its garden meters as links, shows m³ so far and projected for main, garden and wastewater (whole m³, each rounded half up once) only when it has garden meters, the `garden_fee` charge when set, and an alert for open cases linking to the garden page; the garden meter page shows a link to its main, open cases with the three choices, readings, exchanges and the chart, no periods; the add-meter form gains "Main meter (garden meters only)"; the water period form gains "Garden meter fee" (€ per year, net, empty = none) | confirmed
- D11 Garden chart: the main meter's previous and current cycles; garden m³ per month; cost = garden m³ × wastewater net price × (100 + VAT) ÷ 100, no fees (what it saves); projected months by D5 | confirmed
- D12 API: meter items add `main_meter_id` (null) and `garden_conflicts` [{start_date, end_date, excess_milli, reading_id, exchange_id, zeroed}]; POST meters accepts `main_meter_id`; periods add `garden_fee_cents`; the status adds `volumes` [{name: main|garden|wastewater, so_far, projected}] (empty without garden meters) and `charges` may hold `garden_fee`; new POST `/api/utilities/meters/{id}/conflicts/zero` {start_date, end_date} and POST `/api/utilities/readings/{id}/exchange` {old_final_milli} | confirmed
- D13 SPEC: the Utilities bullet (SPEC.md:263) gains a "Garden meters:" part stating D1-D12; no other SPEC line changes | confirmed
- D14 Migration `0017_garden_meters.sql`: ADD COLUMN `utility_meters.main_meter_id` and `utility_periods.garden_fee_cents`, CREATE TABLE `utility_garden_zeroed`; never edits 0001-0016; every utility row survives | confirmed
- D15 Visual gate, pre-authorized: config `visual_recipe` on a temp DB, balance 2026-10-16 and salary day 1, plus a loader in the session scratchpad (never the repo) posting through `/api/utilities` the meters of N09; no real data | confirmed
- D16 Advance link (owner): a `schedule`-mode utility period in force is linked to the active (not dismissed) recurring payment of the same category that is not linked to a debt; that payment's due dates and amount come from the period's remaining scheduled advance dates (after the estimate date, no counted debit within 7 days) and its advance instead of its detected cadence, so the dashboard due list, the payday forecast, Fixed costs, Payoff and the Fixed payments page show the supplier's dates; the Fixed payments row and the utilities card and meter page show the link; a schedule period with no such payment keeps its "<meter> advance" due items; flexible periods and other categories' payments are unchanged; no advance is counted twice (replaces SPEC.md:263's "unless a recurring payment ... is due in the window") | confirmed
- D17 Link span: the supplier's schedule replaces the payment's dates from the period's start through the later of its settlement date and its last advance date; outside that span (no later period in force yet) the payment's own cadence applies, so the 6 forecast pay cycles still show it; the monthly equivalent counts every scheduled date in the span, the due list and pay cycles only the remaining ones | confirmed
- D18 Link resolution: derived on every load from the stored payments and periods (no table, no migration); when several such payments or several schedule periods in force share a category they pair one-to-one in id order (lowest payment id with lowest meter id) and the unpaired keep today's behavior (own cadence; "<meter> advance" items) | confirmed
- D19 Link display: Fixed payments row: Amount = the advance, Next due = the first remaining supplier date (none left: the cadence's next date after the span), a badge "Dates from <meter>" linking to `/utilities/meters/{id}` with the remaining dates as its title; Cadence and the edit, pause and resume forms stay the payment's own (they govern only outside the span); dashboard Fixed costs row: amount = the advance, next due as on Fixed payments. Utilities card and meter page (schedule period in force): "Paid as <payment>" linking to `/recurring#payment-{id}`, else "Forecast as <meter> advance" | confirmed
- D20 API and SPEC: `/api/recurring` items add `advance_meter_id` (null when unlinked) and their `next_due` follows the link; the `/api/utilities` meter status adds `recurring_payment_id` (null); `/api/dashboard` keeps its shape; SPEC gains one new §13 bullet after the Utilities bullet stating D16-D19 and overriding its covered-in-window rule, line 263 itself untouched beyond N06 | confirmed
- D21 Tier: the plan grows to 13 nodes, past M's 10; it stays M, since moving to the L layout now would relocate the briefs and logs of the running N02 and N03 | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/- | 1 | 0 | DONE | |
| N02 | garden link, fee and conflict storage | exec | N01 | sonnet/sonnet | 1 | 1 | DONE | |
| N03 | garden usage and conflicts | exec | N01 | opus/sonnet | 2 | 0 | DONE | |
| N04 | net wastewater and garden fee | exec | N02,N03 | opus/sonnet | 0 | 0 | TODO | |
| N05 | utilities service with gardens | exec | N04 | sonnet/sonnet | 0 | 0 | TODO | |
| N06 | utilities API and SPEC | exec | N05 | sonnet/sonnet | 0 | 0 | TODO | |
| N07 | utilities page and forms | exec | N05 | sonnet/sonnet | 0 | 0 | TODO | |
| N08 | garden meter page and conflict flow | exec | N07 | sonnet/sonnet | 0 | 0 | TODO | |
| N09 | visual check | gate | N06,N08,N13 | -/- | 0 | 0 | TODO | |
| N10 | plan acceptance | check | N09 | -/sonnet | 0 | 0 | TODO | |
| N11 | advance link in the forecast | exec | N05 | opus/sonnet | 0 | 0 | TODO | |
| N12 | Fixed payments link | exec | N08,N11 | sonnet/sonnet | 0 | 0 | TODO | |
| N13 | utilities link and SPEC | exec | N06,N12 | sonnet/sonnet | 0 | 0 | TODO | |

## N01 preflight
Do: Confirm the starting point: verify passes on the untouched tree, the Tailwind CLI builds (the only
  download), 0016 is the latest migration so 0017 is free, `samples/` holds a file for the gate, and the repo
  is writable. Tests need no network. A dirty tree (`.gitignore`, `.claude/launch.json`, this plan) is fine.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-preflight.css" --minify`
  exits 0 and writes outside the repo
- C3 [cmd] `ls src/sonar/migrations/0016_*.sql && test -z "$(ls src/sonar/migrations/0017_* 2>/dev/null)"`
- C4 [cmd] `test -n "$(ls samples/ 2>/dev/null)"`
- C5 [cmd] `test -w .git/index && git status --porcelain >/dev/null`

## N02 garden link, fee and conflict storage
Do: Store the garden link, the garden fee and the zeroed conflict cases, and the reading-to-exchange swap.
  Add migration 0017; `Meter.main_meter_id: int | None = None` and `BillingPeriod.garden_fee_cents: int | None
  = None` (both defaulted so every existing constructor still works); store rules and functions below. The
  API period JSON (`src/sonar/web/api/utilities.py:146`, every BillingPeriod field) then gains
  `garden_fee_cents: null`: add it to the expectations at `tests/web/test_api_utilities.py:39` (PERIOD_DEFAULTS)
  and `:154` (the water round trip); change no API code and no other expectation (N06 owns the API).
Context: D1 link: main exists, kind water, not a garden; the garden's own kind must be water (FieldError
  `main_meter_id`). D2 set only by `add_meter`; `list_meters` returns it. D3 `add_period`/`update_period` on a
  garden meter raise FieldError `meter`; `delete_meter` on a meter that gardens link to raises MeterNotEmpty
  (store.py:62, docstring names garden meters) and deleting a garden meter also deletes its zeroed rows.
  D7 `garden_fee_cents` water only (else FieldError `garden_fee_cents`), >= 0, null = no fee; check it in
  `check_period` (model.py:79). D9 new `zero_garden_interval(conn, meter_id, start, end)` (garden meters only,
  idempotent), `list_zeroed(conn, meter_id) -> list[tuple[date, date]]`, and `reading_to_exchange(conn,
  reading_id, old_final_milli) -> int` that deletes the reading and adds Exchange(its date, old_final, new
  start = its value) in one transaction, the series checked (store.py:93), rolled back on any error.
  D14 `0017_garden_meters.sql`: two ADD COLUMNs (main_meter_id INTEGER REFERENCES utility_meters(id),
  garden_fee_cents INTEGER) and `utility_garden_zeroed(id, meter_id NOT NULL REFERENCES utility_meters(id),
  start_date, end_date, UNIQUE(meter_id, start_date, end_date))`. Period columns: store.py:26-55.
Read: `src/sonar/utilities/model.py`, `src/sonar/utilities/store.py`, `src/sonar/migrations/0016_utilities.sql`,
  `tests/migrations/test_0016.py`, `tests/utilities/test_store.py`, `tests/web/test_api_utilities.py:26-60,142-161`
Write: `src/sonar/migrations/0017_garden_meters.sql`, `src/sonar/utilities/model.py`, `src/sonar/utilities/store.py`,
  `tests/migrations/test_0017.py`, `tests/utilities/test_model.py`, `tests/utilities/test_store.py`,
  `tests/web/test_api_utilities.py`
Test first: strictly per rule, each test written and seen failing before its code: a DB migrated to 0016
  holding a meter, reading, exchange, period and advance date keeps them all after 0017 with `main_meter_id`
  and `garden_fee_cents` null; a garden link to a gas meter is refused.
Done when:
- C1 [cmd] `uv run pytest -q tests/migrations/test_0017.py tests/utilities/test_model.py tests/utilities/test_store.py`
- C2 [review] tests cover: link refused to a missing, non-water or garden main and for a non-water garden;
  a period refused on a garden meter; delete refused for a main with gardens; fee refused on gas and when
  negative and round-tripping through add/update/list_periods; zero idempotent and garden-only; the swap
  keeps the series and rolls back when the old final makes the series drop
- C3 [cmd] `git diff --quiet HEAD -- src/sonar/migrations/0016_utilities.sql src/sonar/migrations/0015_energy_settled.sql src/sonar/web/api/utilities.py`
- C4 [review] `git diff HEAD -- tests/web/test_api_utilities.py` only adds `"garden_fee_cents": None` lines
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N03 garden usage and conflicts
Do: New pure module `src/sonar/utilities/garden.py`: `garden_usage(periods, usages) -> DailyUsage` (the summed
  garden m³ per day by D5), `garden_conflicts(main, gardens) -> list[GardenConflict]` (D8) and
  `garden_cycle_months(periods, usage, today) -> list[ChartMonth]` (D11). No DB, no `date.today()`.
Context: D5 measured where a garden's daily usage (usage.py:55) has the day; after its last point, for each
  main period ending later, `seasonal_daily_kwh("water", replace(period, expected_usage=0), usage, as_of)`
  (settlement.py:303) from the day after its last measured day, so no history gives 0; before its first point
  nothing (0). D8 `gardens: Mapping[int, Series]` (meter id to continuous series, usage.py:16); a case is
  GardenConflict(meter_id, start_date, end_date, excess_milli) for one garden interval [start, end) holding a
  day where the measured garden sum > main measured and that garden used > 0; excess rounded half up once
  (settlement.py:74). D11 the main's cycles via `cycle_months` (settlement.py:140) on periods whose drinking
  charge and both base fees are zero, so cost = m³ × wastewater net price × (100 + VAT) ÷ 100.
  Pins (invented; the D6 periods of tests/utilities/test_settlement.py:660-686): garden A readings 2025-05-31
  0, 2025-12-31 21.400, 2026-10-16 50.300 m³ → `garden_usage` is 1/10 on every day 2025-05-31..2026-12-31
  (2026 sums to 73/2); garden B 2026-01-01 0, 2026-10-16 5.760 → 1/50 per day to 2026-10-15, 0 after;
  A + B sum per day. Conflict: main (2026-03-01, 0), (2026-10-01, 100.000); garden (2026-03-01, 0),
  (2026-06-01, 5.000), (2026-10-01, 65.000) → exactly one case (2026-06-01, 2026-10-01, 2991); two gardens
  (2026-06-01, 0)-(2026-10-01, 55.000) and (2026-06-01, 0)-(2026-10-01, 5.000) under that main → one case
  each, both 2991, though neither alone conflicts. Chart: garden A, today 2026-10-16 → September 2026 is 3 m³
  and 1107 cents.
Read: `src/sonar/utilities/settlement.py`, `src/sonar/utilities/usage.py`, `tests/utilities/test_settlement.py`
Write: `src/sonar/utilities/garden.py`, `tests/utilities/test_garden.py`
Test first: garden A under the D6 periods sums to 73/2 m³ over 2026.
Done when:
- C1 [cmd] `uv run pytest -q tests/utilities/test_garden.py`
- C2 [review] every pin above is a test; an interval with no conflicting day, a garden with no readings and
  days before a garden's first point each have a test; garden.py imports no store, sqlite or web module
- C3 [cmd] `! grep -nE "float|date\.today|datetime\.now" src/sonar/utilities/garden.py`
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N04 net wastewater and garden fee
Do: Teach the cost math the garden deduction and the garden fee. `cost`, `month_figures`, `cycle_months` and
  `meter_status` (settlement.py:110-283) gain a keyword `garden: DailyUsage | None = None` (summed garden m³
  per day, as N03's `garden_usage` returns); MeterStatus gains `volumes: tuple[VolumeFigure, ...] = ()`.
Context: D4 per day drinking on the main m³, wastewater on max(0, main − garden.get(day, 0)); `garden=None`
  changes nothing, so the D6/D7 water pins (test_settlement.py:708) stay green unedited. D6 worst-case
  wastewater = max(0, main worst − garden). D7 `garden_fee_cents` not null → per day with usage a twelfth of
  it over the days in the month (settlement.py:404), times (100 + wastewater VAT) ÷ 100, as a third part and
  ChargeFigure `garden_fee` after drinking and wastewater; the total holds all parts. D10 `volumes` only when
  `garden` is not None: VolumeFigure(name main|garden|wastewater, so_far, projected) in whole m³, each rounded
  half up once; so far over the measured days of the period, projected adds the seasonal days.
  Pins (invented): D6/D7 status (test_settlement.py:703) with garden = 1/10 per day 2025-05-31..2026-12-31:
  so far drinking 22615, wastewater 56163, total 78778; projected 28608, 71020, 99628; worst 99628;
  settlement 20372; volumes so far 160/29/132, projected 203/37/166. Plus garden_fee_cents 1200: garden_fee
  948 so far, 1200 projected; totals 79727 and 100828; settlement 19172. Plus expected_usage 300 on the
  current period: worst total 111031, worst settlement 8969, projection unchanged. Garden + 1/50 per day
  2026-01-01..2026-10-15 with fee 1200: wastewater 54038 and 68895; totals 77601 and 98703; settlement 21297;
  volumes so far 160/35/126, projected 203/42/161. A day where garden > main costs no wastewater m³.
Read: `src/sonar/utilities/settlement.py`, `src/sonar/utilities/model.py`, `tests/utilities/test_settlement.py`
Write: `src/sonar/utilities/settlement.py`, `tests/utilities/test_settlement.py`
Test first: the first pin above (garden 1/10 per day: projected total 99628).
Done when:
- C1 [cmd] `uv run pytest -q tests/utilities/test_settlement.py`
- C2 [cmd] `test -z "$(git diff HEAD -- tests/utilities/test_settlement.py | grep -E '^-[^-]')"` (tests only added)
- C3 [review] every pin above is a test; gas and electricity paths take no `garden`; `month_figures` and
  `cycle_months` cost the net wastewater; no float; each shown figure rounded once
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N05 utilities service with gardens
Do: Wire the gardens into `load_utilities` (service.py:41) so every main water meter is costed net of its
  garden meters and every garden meter gets its chart and its conflict cases. MeterView gains
  `main_meter_id: int | None`, `garden_ids: tuple[int, ...]` and `conflicts: tuple[ConflictCase, ...]`.
Context: D1-D3 a garden meter's view has status None and no periods, so `settlement_summaries`
  (service.py:100) and `meter_cashflows` (service.py:137) skip it with no new code path; check both by test.
  D4-D6 a main with garden meters passes `garden=garden_usage(main periods, garden daily usages)` (N03,
  `src/sonar/utilities/garden.py`) to `meter_status`, `cycle_months` and the ended-period projection
  (service.py:161); a main without garden meters passes None, so its figures are today's. D11 a garden's
  `chart_months` = `garden_cycle_months(main periods, its usage, today)`. D8/D9 ConflictCase(meter_id,
  start_date, end_date, excess_milli, reading_id, exchange_id, zeroed): from `garden_conflicts(main daily
  usage, {garden id: continuous series})`, the closing point on end_date resolved to the reading or exchange
  id of that garden, zeroed from `list_zeroed` (N02, store.py); a main's view holds all its gardens' cases,
  a garden's view its own. `today` stays a parameter.
  Pins (invented, D6/D7 data of tests/utilities/test_settlement.py:652-705 stored in a temp DB with the
  Water bookings): main "Water" with garden "Garden" (readings 2025-05-31 0, 2025-12-31 21.400, 2026-10-16
  50.300) and garden_fee_cents 1200 on the current period → summary settlement 19172; a second meter with
  the same data and no garden → 6903; neither summaries nor cashflows list "Garden".
Read: `src/sonar/utilities/service.py`, `src/sonar/utilities/garden.py`, `src/sonar/utilities/store.py`,
  `tests/utilities/test_service.py`
Write: `src/sonar/utilities/service.py`, `tests/utilities/test_service.py`
Test first: the 19172 settlement summary for the main with one garden meter and the fee.
Done when:
- C1 [cmd] `uv run pytest -q tests/utilities/test_service.py tests/cashflow`
- C2 [review] tests cover: the two pins; a garden's view has status None, chart months and its own cases;
  a case closed by a reading carries its reading_id, one closed by an exchange its exchange_id; a zeroed
  case reads zeroed=True; gas and electricity views unchanged
- C3 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N06 utilities API and SPEC
Do: Expose gardens, the fee, volumes and conflicts on `/api/utilities` and add the two conflict actions;
  write the SPEC part. Keys and routes as D12; errors as today (FieldError 400 with `field`, missing 404,
  MeterNotEmpty 409 with a message naming garden meters; api/utilities.py:174-191).
Context: D12 meter items (api/utilities.py:150) add `main_meter_id` and `garden_conflicts` [{start_date,
  end_date, excess_milli, reading_id, exchange_id, zeroed}]; MeterIn (api/utilities.py:43) takes optional
  `main_meter_id`; PeriodIn and period items add `garden_fee_cents` (null = no fee); the status JSON gains
  `volumes` and may hold the `garden_fee` charge. POST `/api/utilities/meters/{id}/conflicts/zero`
  {start_date, end_date} → 200 with the meter item (store `zero_garden_interval`); POST
  `/api/utilities/readings/{id}/exchange` {old_final_milli} → 201 with the exchange item (store
  `reading_to_exchange`). D13 append to the Utilities bullet (SPEC.md:263), in its terse style, a part
  "Garden meters:" stating D1-D12 as decided in this plan's Decisions; change no other SPEC line.
Read: `src/sonar/web/api/utilities.py`, `src/sonar/utilities/service.py`, `src/sonar/utilities/store.py`,
  `tests/web/test_api_utilities.py`, `SPEC.md:263`
Write: `src/sonar/web/api/utilities.py`, `tests/web/test_api_utilities.py`, `SPEC.md`
Test first: POST a water meter with `main_meter_id` of a water meter returns 201 and GET lists the link.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_api_utilities.py`
- C2 [review] tests cover: link to a gas meter 400 field `main_meter_id`; a period on a garden meter 400;
  deleting a main with gardens 409; `garden_fee_cents` round trip; `volumes` empty without gardens; the
  zero action marks the case zeroed; the exchange action swaps a reading for an exchange and 400s when the
  series would drop
- C3 [review] SPEC.md changes only line 263, and the new part states every rule of D1-D12
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N07 utilities page and forms
Do: Show the gardens on /utilities and add their form fields: the main water card per D10, no card for a
  garden meter, the add-meter "Main meter (garden meters only)" select, and the water period form's
  "Garden meter fee" (€ per year, net, empty = none; `money` prefill, `eur` display). Rebuild sonar.css.
Context: D10 on the main card (utilities.html:35-110, card id `pre`): garden links `[data-garden-meter-id]`
  to `/utilities/meters/{id}`; volumes `[data-volume="main|garden|wastewater"]` with `[data-field="so_far"]`
  and `[data-field="projected"]` in m³, only when the meter has garden meters; the `garden_fee` charge box
  `[data-charge="garden_fee"]` beside drinking and wastewater (utilities.html:75-86); an alert
  `#{pre}-garden-conflicts` with `data-count` of open (not zeroed) cases linking to the garden page. Add-meter
  field `main_meter_id` (METER_FIELDS, pages/utilities.py:45): options "None" plus water meters that are not
  gardens. Period form field `garden_fee` (PERIOD_FIELDS, pages/utilities.py:48; macro utility_forms.html:47)
  for water only; `_period_from` (pages/utilities.py:143) maps it to `garden_fee_cents`; "Start new period"
  (pages/utilities.py:249) copies it. A meter without gardens renders exactly as today. Errors: 400
  re-render with the form open and values kept (pages/utilities.py:404-427). Dashboard card
  (index.html:291-310) needs no template change: its settlement already reflects N05.
  Pins: D6/D7 "Water" with garden "Garden" and fee 1200 (N05 pins), today 2026-10-16 → projected total
  100828, wastewater 71020, garden fee 1200, volumes so far 160/29/132 and projected 203/37/166; a second
  water meter without gardens keeps projected total 113097; the dashboard Utilities card shows 19172 for
  Water and has no Garden row.
Read: `src/sonar/web/pages/utilities.py`, `src/sonar/web/templates/utilities.html`,
  `src/sonar/web/templates/components/utility_forms.html`, `tests/web/test_utilities_page.py:613-700`,
  `tests/web/test_dashboard_page.py:771-860`, `tests/html.py`
Write: `src/sonar/web/pages/utilities.py`, `src/sonar/web/templates/utilities.html`,
  `src/sonar/web/templates/components/utility_forms.html`, `src/sonar/web/static/sonar.css`,
  `tests/web/test_utilities_page.py`, `tests/web/test_utility_meter_page.py`, `tests/web/test_dashboard_page.py`
Test first: the main water card with one garden meter shows `[data-volume="wastewater"] [data-field="so_far"]` 132.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_utilities_page.py tests/web/test_utility_meter_page.py tests/web/test_dashboard_page.py`
- C2 [cmd] `test -z "$(git diff HEAD -- tests/web/test_utilities_page.py | grep -E '^-[^-]')"` (tests only added)
- C3 [review] tests cover every pin, the conflict alert count, the select options, a bad garden fee 400 with
  the value kept, and the fee copied by "Start new period"; hooks are ids and data-*, never classes; no
  inline `<style>`
- C4 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/n07.css" --minify && cmp "$TMPDIR/n07.css" src/sonar/web/static/sonar.css`
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N08 garden meter page and conflict flow
Do: Give a garden meter its own page at `/utilities/meters/{id}` (utility_meter.html): a link to its main,
  its open conflict cases with the three choices, its readings, its exchanges and its chart, and no periods
  or new-period form. Add the two POST routes behind the choices. The main meter page stays as it is.
  Rebuild sonar.css.
Context: D9 per open case `[data-conflict]` with `data-start`, `data-end` and `[data-field="excess"]` in m³:
  "Zero it out" form `[data-action="zero"]` POST `/utilities/meters/{id}/conflicts/zero` (hidden start_date,
  end_date; store `zero_garden_interval`); "Reject the reading" `[data-action="reject"]` posting to the
  existing delete route of the closing reading or exchange (pages/utilities.py:506, :538); "Record as
  exchange" `[data-action="exchange"]` (closing reading only) with field `old_final` (m³, 3 decimals) POST
  `/utilities/readings/{id}/exchange` (store `reading_to_exchange`). Each redirects 303 to the garden page;
  a bad entry re-renders 400 with that form open and its value kept (`_submit`, pages/utilities.py:404).
  Zeroed cases are not listed. D11 the chart reuses `utility_chart` (components/charts.html:192) with the
  garden view's `chart_months`, id `#{pre}-chart`. Link to the main `#main-meter-link`. No inline `<style>`.
  Pins (N03 conflict data, stored): main readings 2026-03-01 0, 2026-10-01 100.000; garden 2026-03-01 0,
  2026-06-01 5.000, 2026-10-01 65.000 → one case 2026-06-01 to 2026-10-01, excess 2,991 m³; after zero it
  out the page lists none; after the exchange with old final 5.000 the 2026-10-01 row is an exchange.
Read: `src/sonar/web/pages/utilities.py`, `src/sonar/web/templates/utility_meter.html`,
  `src/sonar/web/templates/components/charts.html:180-200`, `tests/web/test_utility_meter_page.py`, `tests/html.py`
Write: `src/sonar/web/pages/utilities.py`, `src/sonar/web/templates/utility_meter.html`,
  `src/sonar/web/templates/components/utility_forms.html`, `src/sonar/web/static/sonar.css`,
  `tests/web/test_utility_meter_page.py`
Test first: the garden page of the pin lists one `[data-conflict]` with excess 2,991 and three choices.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_utility_meter_page.py`
- C2 [review] tests cover the pins, a garden page without `[data-period-id]` or new-period form, a case
  closed by an exchange offering only zero and reject, the 400 re-render of a dropping old final, and the
  main meter page unchanged; hooks are ids and data-*
- C3 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/n08.css" --minify && cmp "$TMPDIR/n08.css" src/sonar/web/static/sonar.css`
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N09 visual check
Do: gate, pre-authorized (D15). Start the app per config `visual_recipe` on a temp DB, import the newest
  sample, set balance 2026-10-16 and salary day 1, run a scratchpad loader (never the repo) that creates the
  `fixed` category "Water", imports a synthetic Deutsche Bank CSV shaped like `tests/fixtures/db_girokonto.csv`
  with a neutral counterparty (debits −240,00 on 2026-04-15, 06-15, 08-15, 10-15 and −353,30 on 2026-02-24)
  and its rule, and posts through `/api/utilities`: "Water" with the D6/D7 periods (tests/utilities/
  test_settlement.py:652-705; schedule 04-15..12-15, debit days 55) and garden_fee_cents 1200 on the current
  one, its readings, and garden "Garden" (main Water; readings 2025-05-31 0, 2025-12-31 21.400, 2026-10-16
  50.300); "Water 2" the same (category Water too) without garden or fee. Detection then finds the Water
  debits as one recurring payment of category Water, linked to Water (D16, D18: lowest meter id). Check /,
  /utilities, /recurring and the Water and Garden pages at desktop and 375px, light and dark (read_page first, scaled screenshots only where layout matters). Values
  assume today 2026-10-16; on a later day compare with `/api/utilities` instead.
Done when:
- C1 [visual] the Water card shows Main, Garden and Wastewater m³ (so far 160, 29, 132; projected 203, 37,
  166), Wastewater projected 710,20 €, Garden meter fee 12,00 €, projected total 1.008,28 €, refund 191,72 €
  debited 24.02.2027, and links to Garden; no card for Garden
- C2 [visual] the Water 2 card shows no m³ block and no fee, projected total 1.130,97 € and refund 69,03 €
- C3 [visual] the dashboard Utilities card lists Water 191,72 € and Water 2 69,03 € and no Garden
- C4 [visual] the Garden page shows the link to Water, readings, no exchanges, the chart in m³ and no periods
- C5 [visual] after the loader adds garden "Garden 2" (main Water; readings 2026-09-01 0, 2026-10-01 30.000)
  the Water card alerts one open case and the Garden 2 page shows it with Zero it out, Reject the reading and
  Record as exchange; Zero it out removes the case and the alert
- C6 [visual] the add-meter form offers "Main meter" (None, Water, Water 2) and the Water period form shows
  "Garden meter fee" 12,00; every checked page is readable at 375px in light and dark with nothing cut off
- C7 [visual] /recurring: the Water payment's row shows 240,00 €, next due 15.12.2026 and "Dates from
  Water" linking to the Water page; the Water card and Water page show "Paid as <that payment>" linking
  back to its row; the Water 2 card shows "Forecast as Water 2 advance"
- C8 [visual] after the loader PUTs an extra advance date 2026-10-25 on Water's current period and
  2026-10-28 on Water 2's, the dashboard due list holds the Water payment on 25.10.2026 and "Water 2 advance"
  on 28.10.2026, each 240,00 €, and no "Water advance"; the Water payment's next due on /recurring reads
  25.10.2026

## N10 plan acceptance
Do: Check the whole plan against verify, SPEC §11 and §12, the SPEC §13 Utilities bullet's garden part and
  the new advance-link bullet.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/n10.css" --minify && cmp "$TMPDIR/n10.css" src/sonar/web/static/sonar.css`
- C3 [cmd] `! grep -rnE "float|date\.today|datetime\.now" src/sonar/utilities src/sonar/cashflow`
- C4 [cmd] `test -z "$(git diff --name-only 54ade8a -- src/sonar/migrations | grep -v 0017_garden_meters.sql)"`
- C5 [cmd] `test -z "$(git diff 54ade8a -- tests/utilities/test_settlement.py tests/web/test_utilities_page.py | grep -E '^-[^-]')"`
  (the D6/D7 water pins are untouched)
- C6 [review] SPEC §11 checklist holds and SPEC §12 UI acceptance holds for /utilities, both meter page
  kinds, /recurring and the dashboard card (base.html, component macros, no inline `<style>`, 400 inline errors keeping
  values, `eur` amounts, `money` prefills, usable without script)
- C7 [review] the SPEC §13 Utilities bullet's "Garden meters:" part matches the code for D1-D12
- C8 [review] no tracked file holds a real name, IBAN or meter number; fixtures are invented
- C9 [review] the advance-link bullet after the Utilities bullet matches the code for D16-D20; the old
  covered-in-window rule (cashflow/service.py `_recurring_categories_due`) is gone; no path forecasts a
  linked advance twice (due list, pay cycles, monthly equivalent, Payoff)

## N11 advance link in the forecast
Do: Forecast a linked recurring payment on its supplier's dates. Pure part in `cashflow/forecast.py`:
  `SupplierDates(start, end, dates, remaining, amount_cents)`, `FixedSource.supplier: SupplierDates | None =
  None`, a pure `pair_advances` (D18) and a pure `next_due(source, today)`; `fixed_due`, `_year_total` and
  `_row` (forecast.py:77, :185, :198) take a linked source's occurrences inside [start, end] from it and its
  own periods outside. DB part in `cashflow/service.py`: `advance_links(conn, today) -> dict[int,
  AdvanceLink]` (payment id → payment id and name, meter id and name, supplier), applied by `_fixed_sources`
  (service.py:370) for the dashboard and `load_payoff`; `_advances` (service.py:323) skips linked periods;
  `_recurring_categories_due` (service.py:336) goes.
Context: D16 a `schedule` period in force (`current_period`, utilities/settlement.py) links to the active
  payment (`list_payments`, recurring/store.py:48) of its category not linked to a debt (service.py:389);
  its due dates = the period's remaining advance dates (`MeterCashflow.advance_dates`,
  utilities/service.py:132, already paid-filtered, so no last_paid filter on them) at the period's advance
  each; an unlinked schedule period keeps "<meter> advance"; flexible periods and other categories
  unchanged. D17 span = [period start, later of settlement date and last advance date]; outside it the
  payment's own periods apply; the monthly equivalent counts every scheduled date of the span in its 12
  months, due and pay cycles only the remaining ones. D18 derived on each load, no table; several payments or
  schedule periods per category pair one-to-one in id order; the unpaired keep today's behavior. D19 a linked
  Fixed costs row: amount = the advance, next due = the first remaining date, else the cadence's next after
  the span; day and interval stay its own. `MeterCashflow` (utilities/service.py:126) gains `meter_id` and
  `period: BillingPeriod | None` (the one in force). `today` stays a parameter.
  Pins (helpers at tests/cashflow/test_service.py:953-987, TODAY 2026-09-10, window 09-11..09-24; "Water
  bill" = Water, monthly day 18, 25000): schedule (09-15) with Water bill → due [DueItem("Water bill",
  09-15, 24000)], expected 76000; Water bill on day 28 → the same; a 09-09 Water debit of −24000 → due [];
  "Rent" of another category → Rent and "Water advance"; the Water payment linked to a debt → "Water advance"
  stays; meters "Water" and "Water 2" both in Water with (09-15) and one Water bill → names ["Water 2
  advance", "Water bill"]; schedule (06-15, 09-15, 12-15) with Water bill → its Fixed costs row 24000 next due
  09-15, monthly equivalent 20667.
Read: `src/sonar/cashflow/forecast.py`, `src/sonar/cashflow/service.py`, `src/sonar/utilities/service.py`,
  `src/sonar/recurring/schedule.py`, `tests/cashflow/test_service.py:940-1060`, `tests/cashflow/test_forecast.py`
Write: `src/sonar/cashflow/forecast.py`, `src/sonar/cashflow/service.py`, `src/sonar/utilities/service.py`,
  `tests/cashflow/test_forecast.py`, `tests/cashflow/test_service.py`, `tests/utilities/test_service.py`
Test first: schedule (09-15) with Water bill gives due [DueItem("Water bill", 09-15, 24000)].
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow tests/utilities/test_service.py`
- C2 [review] every pin is a test; only the tests at test_service.py:1020 and :1044 are rewritten (D16),
  no other test line is removed; `load_payoff` and the pay cycles use the links; forecast.py imports no store
- C3 [cmd] `! grep -nE "float|date\.today|datetime\.now" src/sonar/cashflow/forecast.py src/sonar/cashflow/service.py`
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N12 Fixed payments link
Do: Show the advance link on the Fixed payments page and in `/api/recurring`: a linked row shows the
  advance, the supplier's next date and a badge linking to the meter page; every row's tbody gets an anchor
  id. Unlinked rows render exactly as today. Rebuild sonar.css.
Context: D19 per row from `advance_links(conn, today())` (N11, `src/sonar/cashflow/service.py`), keyed by
  payment id: Amount `[data-field="amount"]` (recurring.html:87) shows the link's advance; Next due
  `[data-field="next_due"]` (recurring.html:102 and the mobile copy at :93) = `forecast.next_due` (N11) of the
  payment's FixedSource with the link's supplier; a badge "Dates from <meter>" `[data-field="advance-link"]`,
  an `<a href="/utilities/meters/{meter id}">` beside the debt badge (recurring.html:71-73), with the remaining
  dates (`date` filter) in its `title`; Cadence and the edit, pause and resume drawer stay the payment's own;
  `<tbody data-payment-id>` (recurring.html:64) gains `id="payment-{id}"` (N13 links to it). D20
  `_recurring_item` (api/recurring.py:73) adds `advance_meter_id` (null unlinked) and its `next_due` follows
  the link; `amount_cents` and `periods` stay the payment's own.
  Pins (TODAY 2026-09-23 of tests/web/test_recurring_page.py:16; meter "Water", schedule period 2026-01-01 to
  2026-12-31, dates 06-15, 09-15, 12-15, advance 24000, category Water; "Water bill" via `add_manual` in
  Water, monthly day 18, 25000; "Rent" in another category): the Water bill row shows 240,00, next due
  15.12.2026 and an advance-link to `/utilities/meters/{id}`; Rent has no advance-link and keeps its own
  amount and next due; `/api/recurring` gives Water bill `advance_meter_id` = the meter id and `next_due`
  "2026-12-15", Rent null.
Read: `src/sonar/web/pages/recurring.py`, `src/sonar/web/templates/recurring.html`, `src/sonar/web/api/recurring.py`,
  `src/sonar/cashflow/service.py`, `src/sonar/cashflow/forecast.py`, `tests/web/test_recurring_page.py`,
  `tests/web/test_api_recurring.py`, `tests/html.py`
Write: `src/sonar/web/pages/recurring.py`, `src/sonar/web/templates/recurring.html`, `src/sonar/web/api/recurring.py`,
  `src/sonar/web/static/sonar.css`, `tests/web/test_recurring_page.py`, `tests/web/test_api_recurring.py`
Test first: the Water bill row's `[data-field="next_due"]` reads 15.12.2026.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_recurring_page.py tests/web/test_recurring_page_errors.py tests/web/test_api_recurring.py`
- C2 [review] every pin is a test; a debt-linked payment of the category has no advance-link; hooks are ids
  and data-*, never classes; no inline `<style>`
- C3 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/n12.css" --minify && cmp "$TMPDIR/n12.css" src/sonar/web/static/sonar.css`
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N13 utilities link and SPEC
Do: Show the advance link on /utilities, on the meter page and in `/api/utilities`, and write the SPEC
  bullet. Meters with flexible or no current period render as today. Rebuild sonar.css.
Context: D19 a meter whose period in force is `schedule` shows, by its Advance stat (utilities.html:65-69,
  card prefix `pre` = "meter-{id}", utilities.html:38): linked → "Paid as <payment name>" `#{pre}-recurring-link`,
  an `<a href="/recurring#payment-{payment id}">` (N12 gave the row that id); unlinked → "Forecast as <meter>
  advance" `#{pre}-advance-item`; flexible and garden meters show neither. The meter page shows the same on
  the period in force (utility_meter.html:139-141) as `[data-field="recurring"]`. Links come from
  `advance_links(conn, today())` (N11, `src/sonar/cashflow/service.py`), inverted to meter id in
  pages/utilities.py. D20 the `/api/utilities` meter status (api/utilities.py) adds `recurring_payment_id`
  (null when unlinked or flexible). SPEC: one new bullet right after the Utilities bullet (SPEC.md:263, its
  garden part included), titled "Utility advances in Fixed payments (§6, §9, §13 Utilities; overrides the
  Utilities bullet's 'unless a recurring payment (not linked to a debt) in that period's category is due in
  the window')", stating D16-D20 in the SPEC's terse style; no other SPEC line changes.
  Pins (N12's "Water" meter and "Water bill"; a second schedule meter "Water 2" in Water; a flexible gas
  meter): the Water card's recurring-link reads "Water bill" with href `/recurring#payment-{id}`; the Water
  2 card's advance-item reads "Forecast as Water 2 advance"; the gas card has neither; the Water page's
  `[data-field="recurring"]` links to the row; the API status `recurring_payment_id` is the payment id for
  Water and null for Water 2 and gas.
Read: `src/sonar/web/pages/utilities.py`, `src/sonar/web/templates/utilities.html`,
  `src/sonar/web/templates/utility_meter.html`, `src/sonar/web/api/utilities.py`, `src/sonar/cashflow/service.py`,
  `tests/web/test_utilities_page.py`, `tests/web/test_utility_meter_page.py`, `tests/web/test_api_utilities.py`, `SPEC.md:263`
Write: `src/sonar/web/pages/utilities.py`, `src/sonar/web/templates/utilities.html`,
  `src/sonar/web/templates/utility_meter.html`, `src/sonar/web/api/utilities.py`, `src/sonar/web/static/sonar.css`,
  `tests/web/test_utilities_page.py`, `tests/web/test_utility_meter_page.py`, `tests/web/test_api_utilities.py`, `SPEC.md`
Test first: the Water card's `#meter-{id}-recurring-link` reads "Water bill".
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_utilities_page.py tests/web/test_utility_meter_page.py tests/web/test_api_utilities.py`
- C2 [cmd] `test -z "$(git diff HEAD -- tests/web/test_utilities_page.py | grep -E '^-[^-]')"` (tests only added)
- C3 [review] every pin is a test; hooks are ids and data-*; no inline `<style>`; the SPEC diff adds exactly
  one bullet after line 263 and it states every rule of D16-D20
- C4 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/n13.css" --minify && cmp "$TMPDIR/n13.css" src/sonar/web/static/sonar.css`
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## Log

### N01 try 1 · 2026-10-16
check: PASS 5/5

### N02 try 1 · 2026-10-16
exec: BLOCKED · C1/C3 pass (99 tests), but Verify fails: new BillingPeriod.garden_fee_cents appears in the API period JSON, so tests/web/test_api_utilities.py (PERIOD_DEFAULTS, WATER_PERIOD expectations) needs garden_fee_cents: None, outside Write

### N02 replan 1 · 2026-10-16
plan: REPLANNED
- cause: BillingPeriod.garden_fee_cents surfaces in API period JSON (api/utilities.py:146), breaking expectations in tests/web/test_api_utilities.py outside Write
- brief adds tests/web/test_api_utilities.py to Write, limited to adding garden_fee_cents None at :39 and :154 (new C4 review); API code stays untouched (C3)
- Test first now states strict red-before-code order

### N03 try 1 · 2026-10-16
exec: DONE · test_garden 13 passed; full suite 1951 passed, 3 failed outside Write (test_store garden period, test_api_utilities x2: garden_fee_cents) from concurrent uncommitted model.py/store.py edits
- new pure garden.py: garden_usage, garden_conflicts, garden_cycle_months plus test_garden.py; ruff clean
- projection keeps only each later period's own days; conflicts compare only days the main measured; excess is the gardens' total over the main on the interval's conflict days
- chart zeroes drinking price and both base fees, then reuses cycle_months on the garden's raw daily usage
check: FAIL C4
- C4 exit 1: 1 failed, 1314 passed, 3 warnings in 21.53s

### N02 try 1 · 2026-10-16
exec: DONE · 1954 passed
- migration 0017, Meter.main_meter_id, BillingPeriod.garden_fee_cents, store link/fee/zeroed/reading_to_exchange rules with tests
- API test expectations gain garden_fee_cents: None only
check: PASS 3/3
verify: PASS

### N03 try 2 · 2026-10-16
exec: DONE · 1954 passed
- No code change in try 2: the try-1 C4 failure no longer reproduces; full suite passes twice and ruff is clean
- garden.py and test_garden.py (13 tests) from try 1 kept as is
check: PASS 3/3
verify: PASS
