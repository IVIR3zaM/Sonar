# Energy monitor
status: RUNNING
created: 2026-10-12 · updated: 2026-10-15
goal: Per gas or electricity meter, Sonar shows the cost so far, the advances paid, the projected settlement and a suggested advance, from hand-entered readings, meter exchanges and billing periods, on an Energy page, a dashboard card and in the forecast.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: The owner tracks gas and electricity advances (Abschläge) in a spreadsheet to guess whether the yearly settlement will bring a back-payment or a refund. Sonar takes this over: from meter readings, physical meter exchanges and the tariff of each billing period it works out what the energy used so far cost, compares it with the advances actually booked in the period's category, and projects the settlement and the advance that would bring it to about zero.

In scope: a new SPEC §13 Energy bullet; a feature package `src/sonar/energy/` (model, pure usage and settlement math, store, service); migration `0014_energy.sql` for meters, exchanges, readings and billing periods; a JSON API under `/api/energy` so Claude can load the sheet's history after the build; an Energy page with per-meter status, readings, exchange and period forms and one combined usage and cost chart per meter with value-label and trend toggles; a dashboard Energy card; the projected settlement as a due item or inflow in the payday forecast.

Out of scope: importing from Google Sheets, smart-meter feeds, changes to categorization rules or the categorization package, loading the owner's real sheet history (done later through the API), seasonal forecasting models beyond D7, any change to how the advances themselves are forecast (they stay recurring payments).

Constraints: AGENTS.md rules: strict TDD, KISS, functional core with `today` as a parameter, money in integer cents, sub-cent prices and factors in integer units (D2), no float, dates as `datetime.date`, new migration only, hand-entered data survives upgrades, `tests/test_architecture.py` stays green, routes only in `web/pages/energy.py` and `web/api/energy.py`, page tests on ids and `data-*` through `tests/html.py`, no inline `<style>`, `sonar.css` rebuilt and committed, `/api/*` behind the existing sign-in gate. Decisions D1-D14.

Definition of done: verify passes; on a temp DB the Energy page, the API, the dashboard card and the forecast entry work with synthetic data; the visual gate passes for the Energy page and dashboard at desktop and 375px, light and dark, with both chart toggles; the final check passes SPEC §11 and §12.

## Decisions

- D1 Scope from the request: package `src/sonar/energy/` (`model.py`, `usage.py`, `settlement.py`, `store.py`, `service.py`), migration `src/sonar/migrations/0014_energy.sql`, page `src/sonar/web/pages/energy.py` + `templates/energy.html`, API `src/sonar/web/api/energy.py`, one SPEC §13 "Energy" bullet; meters are a list of kind `gas` or `electricity` | confirmed
- D2 Units: readings integer thousandths of the meter unit (`value_milli`, m³ for gas, kWh for electricity); unit price integer millionths of a euro per kWh (`unit_price_micro`, 31,83 ct = 318300; forms take ct/kWh with up to 4 decimals); Zustandszahl `state_factor_e4` and Brennwert (kWh/m³) `calorific_value_e4` integer ten-thousandths (0,9653 = 9653; 11,5 = 115000); base fee per month and advance per month integer cents; expected yearly usage whole kWh; intermediate math in `fractions.Fraction`, each shown figure rounded half up once to whole cents or whole kWh | confirmed
- D3 Exchanges: an exchange is (meter, date, old_final_milli, new_start_milli); a reading's continuous value = its value + Σ(old_final − new_start) of the meter's exchanges dated before it, and the exchange itself is the point (date, old_final + earlier offsets); at most one reading and one exchange per meter per date; a reading on an exchange date is a 400; every write re-checks the meter's whole continuous series and rejects a drop with a 400 naming the date, writing nothing | confirmed
- D4 Days and months: an interval between consecutive series points [d0, d1) spreads its usage evenly over its d1−d0 days; month figures sum their days; the chart and month figures include only calendar months fully inside [first point, last point) and fully covered by billing periods; gas kWh per day = m³ × state factor × calorific value of the period in force that day | confirmed
- D5 Base fee and the sheet checks: cost = base fee × months + kWh × unit price, per day by the period in force, where months = Σ over calendar months of covered days ÷ days in that month (one full calendar month = 1 × fee). Test pins: 541 kWh in one full month at 31,8189 ct/kWh + 10,41 € = 18255 ct (182,55 €; at exactly 31,83 ct it is 182,61 €, so the sheet's price is about 31,8189 ct); 18 m³ × 0,9653 × 11,5 × 9,86 ct + 9,95 € = 2965 ct (the sheet's 29,66 € comes from a Brennwert just above 11,5) | confirmed
- D6 Billing period: meter, `start_date`, `settlement_date` (inclusive last day), `base_fee_cents`, `unit_price_micro`, `state_factor_e4` and `calorific_value_e4` (required for gas, null for electricity), `advance_cents`, `expected_kwh`, `category` (stored as the category id, read back as its name; a deleted category reads as none and the period counts no payments); a meter's periods never overlap; the current period is the one containing today; with none the meter shows its latest period as settled, with no projection and nothing in the forecast; a new period after an Abrechnung is just another period, history stays | confirmed
- D7 Status of the current period: cost so far = cost from the period start (or the first series point, if later) to the latest series point in the period, shown "as of" that date; paid so far = Σ |amount| of debits in the period's category booked from period start to today, credits ignored; left = paid − cost so far; daily rate = kWh so far ÷ days so far; projected cost = cost so far + the remaining days to the settlement date at the daily rate, with their base fee; advance day = day of month of the latest advance debit in the period (none: the start date's day); remaining advances = advance_cents × the occurrences of that day after the latest advance debit (none: from the start date on) up to the settlement date; settlement = paid + remaining advances − projected cost (positive refund, negative back-payment); worst case = the same with the remaining days at the highest of the daily rate, expected_kwh ÷ 365, and last year's daily kWh on the same calendar days when the series covers them; suggested advance = (projected cost − paid) ÷ remaining advance count, rounded up to whole euros, none without a remaining advance; no series point after the period start → no cost or projection, paid still shown | confirmed
- D8 Chart: one chart per meter over its last 24 plotted months: usage as sky columns (kWh) and cost as an amber line (€), each scaled to its own peak, with a legend; checkboxes "Show values" and "Show trend" (both off by default) show the per-point value labels and a least-squares straight trend line per series, done in CSS only (the checkbox plus Tailwind `has-[…]`/`group-has-[…]` variants), so no script; a new `energy_chart` macro in `components/charts.html` with helpers in `web/charts.py`, existing macros unchanged | confirmed
- D9 Page: `/energy`, nav item "Energy" after "Payoff"; an Add meter card (name, kind) and, per meter, a card with stats (cost so far, paid so far, left, projected settlement with worst case and settlement date, suggested advance), the chart, a Readings table newest first (date, reading, usage since previous, kWh per day) with an Edit drawer and Delete (`hx-confirm`) per row and an Add reading form, Exchanges (list, edit, delete, add), Billing periods (list, edit drawer, delete, a "Start new period" form prefilled from the latest period with start = its settlement date + 1); Delete meter only when it has no readings, exchanges or periods; invalid input re-renders with status 400, the inline `#form-error` and the entered values (SPEC §12) | confirmed
- D10 API: `GET /api/energy` → `{meters: [{id, name, kind, status, periods, exchanges, readings}]}` in the stored integer units (D2), dates ISO, `category` by name; `POST /api/energy/meters` {name, kind} 201, `PUT /api/energy/meters/{id}` {name}, `DELETE /api/energy/meters/{id}` (409 when not empty); `POST /api/energy/meters/{id}/readings` {date, value_milli}, `PUT`/`DELETE /api/energy/readings/{id}`; `POST /api/energy/meters/{id}/exchanges` {date, old_final_milli, new_start_milli}, `PUT`/`DELETE /api/energy/exchanges/{id}`; `POST /api/energy/meters/{id}/periods` {start_date, settlement_date, base_fee_cents, unit_price_micro, state_factor_e4, calorific_value_e4, advance_cents, expected_kwh, category}, `PUT`/`DELETE /api/energy/periods/{id}`; writes answer the item (201 on create), errors 400 {error, field}, 404 {error}, 409 {error}, 422 for an unknown key or wrong JSON type, as SPEC §13 API parity; page and API share the store validation (`model.FieldError` with `.field`); sign-in comes from the existing gate | confirmed
- D11 Dashboard and forecast: an "Energy" card after the Installments and loans card lists each meter with a current period: "Refund X" or "Back-payment X" with the settlement date, the worst case and the suggested advance; absent when no meter has a current period; computed as of the estimate date (SPEC §13 Estimate date), the Energy page as of today. A settlement date inside the forecast window [estimate date + 1, payday − 1] adds the settlement as a due item "<meter> settlement" when negative or an inflow "<meter> settlement" when positive, so expected, worst and best move with it; `/api/dashboard` gains `energy` | confirmed
- D12 One category per period, assumed distinct across meters: if gas and electricity advances share one category both meters count all of it; no validation for this | confirmed
- D13 Visual gate (pre-authorized): config `visual_recipe` on a temp DB, plus a scratch loader in the session scratchpad (never the repo) that posts synthetic data through `/api/energy`: meters "Gas" (one exchange) and "Electricity", about 14 months of readings each, one settled and one current period each with a seeded `fixed` category, the current settlement dates inside the forecast window; no real readings or names | confirmed
- D14 Loading the owner's sheet history is a separate request after this plan, through the API | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/- | 1 | 1 | DONE | |
| N02 | energy model, usage and SPEC | exec | N01 | sonnet/sonnet | 1 | 0 | DONE | |
| N03 | migration and energy store | exec | N02 | sonnet/sonnet | 1 | 0 | DONE | |
| N04 | settlement math | exec | N02 | sonnet/opus | 1 | 0 | DONE | |
| N05 | energy service and JSON API | exec | N03,N04 | sonnet/sonnet | 0 | 0 | TODO | |
| N06 | Energy page | exec | N05 | sonnet/sonnet | 0 | 0 | TODO | |
| N07 | usage and cost chart | exec | N06 | sonnet/sonnet | 0 | 0 | TODO | |
| N08 | dashboard card and forecast | exec | N07 | sonnet/sonnet | 0 | 0 | TODO | |
| N09 | visual check | gate | N08 | -/- | 0 | 0 | TODO | |
| N10 | plan acceptance | check | N09 | -/sonnet | 0 | 0 | TODO | |

## N01 preflight
Do: Confirm the starting point before any work: verify passes on the untouched tree, the Tailwind CLI builds
  (the only download), 0013 is the latest migration so 0014 is free for the energy tables, and the repo is
  writable. Tests need no network. A dirty working tree (`.gitignore`, `.claude/launch.json`, this plan) is fine.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-preflight.css" --minify`
  exits 0 and writes outside the repo
- C3 [cmd] `ls src/sonar/migrations/0013_*.sql && test -z "$(ls src/sonar/migrations/0014_* src/sonar/migrations/0015_* 2>/dev/null)"`
- C4 [cmd] `test -w .git/index && git status --porcelain >/dev/null` exits 0

## N02 energy model, usage and SPEC
Do: Create `sonar.energy` with `model.py` (frozen dataclasses `Meter`, `Reading`, `Exchange`, `BillingPeriod`,
  `FieldError(ValueError)` with a `field` attribute and a human message, and `check_period`/`check_periods`)
  and `usage.py`, pure functions: `continuous_series`, `check_series` and `daily_usage` in meter units. Add
  the SPEC §13 "Energy" bullet. No sqlite, no web imports, no float, no clock.
Context: D2 units: `value_milli`, `old_final_milli`, `new_start_milli`; period fields as D6 with
  `unit_price_micro`, `state_factor_e4`, `calorific_value_e4`, cents, `expected_kwh`, `category: str | None`.
  D3 continuous value = value + Σ(old_final − new_start) of exchanges dated before it; the exchange is the
  point (date, old_final + earlier offsets); `check_series` raises FieldError("date") for a reading on an
  exchange date and FieldError("value") naming the first date where the series drops. D4 `daily_usage`
  returns `dict[date, Fraction]` of meter units per day over [first point, last point), each interval
  spread evenly. D6 `check_period(period, kind)`: settlement_date ≥ start_date, positive price, non-negative
  fee/advance/expected, gas needs both factors > 0, electricity has both null; `check_periods` rejects
  overlap (field "start_date"). SPEC: one bullet at the end of §13, after SPEC.md:260 (Public pages), stating D2-D11 in SPEC style.
Read: `.plan/2026-10-12-energy-monitor.md` (Decisions only), `src/sonar/debts/model.py:1-60`, `SPEC.md:225-260`, `tests/test_architecture.py`
Write: `src/sonar/energy/__init__.py`, `src/sonar/energy/model.py`, `src/sonar/energy/usage.py`, `tests/energy/__init__.py`, `tests/energy/test_usage.py`, `tests/energy/test_model.py`, `SPEC.md`
Test first: readings 1 Jan 1000.000 m³ and 1 Mar 30.000, exchange 1 Feb old 1050.000 new 0.000 give the
  series 1000000, 1050000, 1080000 and daily usage 50/31 m³ on each January day, 30/28 on each February
  day; `usage.py` does not exist yet, so it fails.
Done when:
- C1 [cmd] `uv run pytest -q tests/energy/test_usage.py` passes: the exchange example; two exchanges in a row;
  a reading on an exchange date raises FieldError field "date"; a drop raises field "value" naming its date;
  no exchanges is the plain series; fewer than 2 points gives empty daily usage
- C2 [cmd] `uv run pytest -q tests/energy/test_model.py` passes: overlapping periods, end before start, a gas
  period without factors and an electricity period with them each raise FieldError with the right field
- C3 [review] SPEC.md has exactly one new §13 Energy bullet covering units, exchanges, day allocation, base
  fee months, periods, status and projection, chart toggles, page, API and dashboard/forecast as D2-D11
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N03 migration and energy store
Do: Add `0014_energy.sql` with tables `energy_meters` (name unique, kind gas|electricity), `energy_readings`,
  `energy_exchanges` (each unique per meter and date) and `energy_periods` (category_id nullable), and
  `energy/store.py`: list/add/rename/delete meters, and list/add/update/delete readings, exchanges and
  periods, returning `sonar.energy.model` dataclasses. Every write validates the meter's resulting rows with
  `usage.check_series` and `model.check_period(s)` before committing; a FieldError writes nothing.
Context: D3 one reading and one exchange per meter per date (duplicate → FieldError "date"). D6 `category`
  is a name in the model: the store writes `categories.id` (unknown name → FieldError "category") and reads
  the name with a LEFT JOIN, so a deleted category reads None. D9/D10 deleting a meter with readings,
  exchanges or periods raises `MeterNotEmpty`; unknown ids raise `EnergyNotFound(LookupError)`. New tables
  only: existing data is untouched. Style: `src/sonar/debts/store.py`, migration tests like
  `tests/migrations/test_0011.py` (0012 and 0013 are the bank-sync migrations; energy is 0014).
Read: `src/sonar/energy/model.py`, `src/sonar/energy/usage.py`, `src/sonar/debts/store.py`, `src/sonar/migrations/0013_bank_merge.sql`, `tests/migrations/test_0011.py`, `src/sonar/migrations/0006_categories.sql`
Write: `src/sonar/migrations/0014_energy.sql`, `src/sonar/energy/store.py`, `tests/migrations/test_0014.py`, `tests/energy/test_store.py`
Test first: adding meter "Gas" (gas) and a reading 1 Jan 1000.000 then listing returns that Reading; the
  store does not exist yet, so it fails.
Done when:
- C1 [cmd] `uv run pytest -q tests/migrations/test_0014.py` passes: the migration applies on a DB at 0013
  with existing transactions, categories and debts unchanged, and creates the four tables
- C2 [cmd] `uv run pytest -q tests/energy/test_store.py` passes round trips for every add/update/delete; a
  dropping reading, a reading on an exchange date, a duplicate date, an overlapping period and an unknown
  category each raise FieldError and leave the tables unchanged; deleting a non-empty meter raises
  MeterNotEmpty; a deleted category reads back as None
- C3 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N04 settlement math
Do: Add `energy/settlement.py`, pure: `daily_kwh` (meter units per day to kWh per day by the period in force),
  `cost` over a date range, `month_figures` (month, kWh, cost cents) and `current_period(periods, today)`,
  and `meter_status(...)` returning a `MeterStatus` with as_of, cost_so_far_cents, paid_cents, left_cents,
  projected_cost_cents, remaining_advances_cents, settlement_cents, worst_settlement_cents,
  suggested_advance_cents (None where D7 says none). Inputs: kind, periods, daily usage from
  `usage.daily_usage`, the current period's advance debits as (date, cents > 0), today.
Context: D2 Fraction math, round half up once per shown figure, no float. D4 gas kWh = m³ × state_factor_e4 ×
  calorific_value_e4 ÷ 10^8 per day; days outside every period have no kWh/cost; month figures only for
  calendar months fully covered by daily usage and periods. D5 cost = base fee × months (Σ covered days ÷
  days in month) + kWh × unit_price_micro; pins 541 kWh in one full month at 318189 µ€/kWh + 1041 ct = 18255
  ct, and 18 m³ × 9653 × 115000 at 98600 µ€ + 995 ct = 2965 ct. D6 current period contains today, else None.
  D7 every status rule, verbatim: cost so far from max(start, first point) to the latest point in the
  period; paid = Σ advances in [start, today]; left = paid − cost so far; daily rate = kWh so far ÷ days so
  far; projected cost = cost so far + remaining days to settlement at that rate plus their base fee;
  advance day = day of the latest advance (none: start's day); remaining advances = advance_cents × that
  day's occurrences after the latest advance (none: from start) through settlement; settlement = paid +
  remaining − projected (positive refund); worst = remaining days at max(rate, expected_kwh ÷ 365, last
  year's kWh on the same days when covered; 29 Feb → 28 Feb); suggested = ceil to whole euros of
  (projected − paid) ÷ remaining count, None without one; no point after start → cost and projection None.
Read: `src/sonar/energy/model.py`, `src/sonar/energy/usage.py`, `src/sonar/money.py`
Write: `src/sonar/energy/settlement.py`, `tests/energy/test_settlement.py`
Test first: the electricity pin, 541 kWh in March at 318189 µ€/kWh and 1041 ct fee, costs 18255 ct;
  `settlement.py` does not exist yet, so it fails.
Done when:
- C1 [cmd] `uv run pytest -q tests/energy/test_settlement.py -k "cost or month"` passes: both D5 pins; a fee for
  half of a 30-day month is half the fee; a range across a price change prices each day by its period;
  months not fully covered are left out
- C2 [cmd] `uv run pytest -q tests/energy/test_settlement.py -k status` passes hand-computed cases: refund,
  back-payment, worst case taken from last year's same days, from expected_kwh, and equal to the projection
  when the rate is highest; suggested advance rounded up and None on the settlement day; credits and
  advances before start ignored; no reading after start gives None cost and projection but a paid sum
- C3 [review] settlement.py has no float, no `date.today`, no sqlite or web import, and one rounding per figure
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N05 energy service and JSON API
Do: Add `energy/service.py` with `load_energy(conn, today) -> list[MeterView]` (meter, periods, exchanges,
  readings, current-period `MeterStatus` or None, `month_figures`) using the store, `usage`, `settlement`
  and the current period category's debits from `categorization.store.transactions_with_category`. Add
  `web/api/energy.py` with every D10 route and mount it in `web/api/__init__.py`.
Context: D7 advances = debits (amount < 0, as positive cents) of the period's category booked in [start,
  today]; credits ignored. D10 routes and shapes: `GET /api/energy` → `{meters: [...]}` with `status`
  (MeterStatus fields or null), periods, exchanges, readings in stored integer units, ISO dates, `category`
  by name; `POST /api/energy/meters` {name, kind} 201; `PUT /api/energy/meters/{id}` {name};
  `DELETE /api/energy/meters/{id}` 409 when not empty; readings {date, value_milli}, exchanges {date,
  old_final_milli, new_start_milli}, periods {start_date, settlement_date, base_fee_cents,
  unit_price_micro, state_factor_e4, calorific_value_e4, advance_cents, expected_kwh, category}, each POST
  under `/api/energy/meters/{id}/…` and PUT/DELETE at `/api/energy/{readings|exchanges|periods}/{id}`;
  writes answer the item (201 on create); FieldError → 400 {error, field}; EnergyNotFound → 404 {error};
  MeterNotEmpty → 409 {error}; unknown key or wrong JSON type → 422 (strict pydantic models, see
  `src/sonar/web/api/_common.py:14-46`). Sign-in needs nothing new: /api/* sits behind the gate.
Read: `src/sonar/energy/store.py`, `src/sonar/energy/settlement.py`, `src/sonar/energy/usage.py`, `src/sonar/web/api/_common.py`, `src/sonar/web/api/__init__.py`, `src/sonar/web/api/debts.py:160-302`, `tests/web/test_api_debts.py:1-60`, `tests/web/test_auth_api_token.py:1-40`
Write: `src/sonar/energy/service.py`, `src/sonar/web/api/energy.py`, `src/sonar/web/api/__init__.py`, `tests/energy/test_service.py`, `tests/web/test_api_energy.py`
Test first: POST a gas meter, a period with category "Utilities" and two readings, add a "Utilities" debit
  of −100,00 €, and `GET /api/energy` lists the meter with `status.paid_cents` 10000; the route does not
  exist yet, so it fails.
Done when:
- C1 [cmd] `uv run pytest -q tests/energy/test_service.py` passes: paid counts only the current period
  category's debits in [start, today]; no current period gives status None; month figures are present
- C2 [cmd] `uv run pytest -q tests/web/test_api_energy.py` passes a create, read, update and delete for meters,
  readings, exchanges and periods, and the error cases 400 with field (drop, exchange-date reading,
  overlap, unknown category, missing gas factor), 404 unknown id, 409 non-empty meter delete, 422 unknown
  key and wrong type, and 401 without a session when sign-in is on
- C3 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N06 Energy page
Do: Add `web/pages/energy.py` and `templates/energy.html` at `/energy` (D9) without the chart, the nav item
  "Energy" after "Payoff" in `base.html`, the router in `web/app.py`, a decimal parser for the forms, and
  rebuild `sonar.css`. Every write goes through `energy/store.py`; GET and error paths share one render
  helper; POST success redirects 303 to `/energy`.
Context: D9 Add meter card (name, kind); per meter `<section data-meter-id>` card: stats `#…-cost-so-far`,
  paid, left, projected settlement (refund/back-payment wording, worst case, settlement date), suggested
  advance (ids prefixed per meter, `data-cents` via `eur`); Readings table newest first (date, reading,
  usage since previous, kWh per day) with an Edit `<details>` drawer and Delete (`hx-confirm`) per row and
  an Add reading form; Exchanges list with edit, delete, add; Billing periods list with an edit drawer,
  delete and "Start new period" prefilled from the latest period (start = its settlement date + 1);
  Delete meter shown only for an empty meter. Forms: readings in m³/kWh with up to 3 decimals, price in
  ct/kWh with up to 4, factors with up to 4, money with `money` prefills; one `parse_scaled(text, places)`
  in `web/forms.py` accepting one "." or ","; category is a select of the categories. FieldError and parse
  errors re-render with 400, `#form-error` and the entered values (SPEC §12). Displayed amounts `eur`,
  dates `date`. No inline `<style>`.
Read: `src/sonar/energy/service.py`, `src/sonar/energy/store.py`, `src/sonar/web/pages/debts.py`, `src/sonar/web/templates/debts.html`, `src/sonar/web/templates/base.html:18-30`, `src/sonar/web/app.py:100-125`, `src/sonar/web/forms.py`, `tests/html.py`, `tests/web/test_debts_page.py:1-60`
Write: `src/sonar/web/pages/energy.py`, `src/sonar/web/templates/energy.html`, `src/sonar/web/templates/base.html`, `src/sonar/web/app.py`, `src/sonar/web/forms.py`, `src/sonar/web/static/sonar.css`, `tests/web/test_energy_page.py`, `tests/web/test_forms.py`
Test first: after adding a gas meter and a reading through the store, GET /energy shows a
  `[data-meter-id]` section with that reading's row; the route does not exist yet, so it fails.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_energy_page.py` passes: status stats with `data-cents`; add, edit and
  delete for readings, exchanges and periods via the page; add meter and delete of an empty meter; a
  dropping reading and a bad price each answer 400 with `#form-error` and the entered value kept; the
  new-period form is prefilled with the day after the latest settlement date
- C2 [cmd] `uv run pytest -q tests/web/test_forms.py tests/web/test_templates_hygiene.py tests/web/test_shell.py`
  passes, with `parse_scaled` cases for "12,345", "12.3456" at 4 places, too many decimals and blank
- C3 [smoke] `uv run sonar` on a temp DB answers 200 on /energy with the nav item marked current
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N07 usage and cost chart
Do: Add an `energy_chart` macro to `components/charts.html` and its helpers to `web/charts.py`, and render one
  chart per meter on the Energy page from `MeterView.month_figures` (last 24). Rebuild `sonar.css`.
Context: D8 usage as sky columns (kWh) and cost as an amber line (€), each series scaled to its own peak (not
  the shared scale of `line_points`, src/sonar/web/charts.py:193-212), a legend naming both with units;
  per point a value label (whole kWh, `compact_eur` for cost); a least-squares straight trend line per
  series computed in `web/charts.py` with integer or Fraction math; two checkboxes "Show values" and "Show
  trend", both unchecked by default, that show the labels and trend lines through CSS only (Tailwind
  `has-[…]`/`group-has-[…]` variants on a wrapper), no `<script>`; the svg has `role="img"`, a `<title>`
  and an aria-label; stable hooks: `[data-energy-chart]`, `[data-series="usage"]`, `[data-series="cost"]`,
  `[data-trend]`, `[data-value-label]`, inputs `[data-toggle="values"]` and `[data-toggle="trend"]`; fewer
  than 2 months shows an empty-state line instead. Existing macros and their tests stay unchanged. Axis
  labels with `charts.month_label`.
Read: `src/sonar/web/charts.py`, `src/sonar/web/templates/components/charts.html`, `src/sonar/web/templates/energy.html`, `src/sonar/energy/service.py`, `tests/web/test_charts.py:1-40`, `src/sonar/web/static/src/app.css`
Write: `src/sonar/web/charts.py`, `src/sonar/web/templates/components/charts.html`, `src/sonar/web/templates/energy.html`, `src/sonar/web/static/sonar.css`, `tests/web/test_charts.py`, `tests/web/test_energy_page.py`
Test first: `charts.trend([1, 2, 3])` gives a rising straight line through the points' mean; it does not exist
  yet, so it fails.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_charts.py -k "trend or own_scale"` passes: trend of a straight
  series is that series, of a flat one flat; each series' peak fills the height on its own scale
- C2 [cmd] `uv run pytest -q tests/web/test_energy_page.py -k chart` passes: one `[data-energy-chart]` per meter
  with both series, one value label per point, a trend per series, both toggles unchecked, no `<script>`
  in the page, and the empty state with fewer than 2 months
- C3 [review] the toggles work without JS (CSS `has`/`group-has` variants present in rebuilt `sonar.css`);
  existing chart macros are unchanged
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N08 dashboard card and forecast
Do: Add `energy.service.settlement_summaries(conn, today)` (meter name, settlement date, settlement,
  worst settlement, suggested advance, per meter with a current period and a projection), a `Dashboard.energy`
  field filled as of the estimate date, the projected settlements in the forecast window as due items or
  inflows in `cashflow/service.py`, and an "Energy" card in `index.html` after `#debts-card`. Rebuild
  `sonar.css`.
Context: D11 the card `#energy-card` lists rows `[data-meter]` with "Refund X" (positive) or "Back-payment
  X" (negative) and the settlement date, the worst case and the suggested advance; absent when the list is
  empty. Estimate date = balance as-of, else today (src/sonar/cashflow/service.py:131). A summary whose
  settlement date is in [estimate date + 1, payday − 1] (window at service.py:164-167) adds
  `DueItem("<meter> settlement", date, |cents|)` to `due` when negative or to `inflows` when positive,
  before the totals, projection and expected are computed, so they include it; zero adds nothing.
  `/api/dashboard` serializes the new field through `_jsonable` (src/sonar/web/api/cashflow.py:57-65).
Read: `src/sonar/cashflow/service.py`, `src/sonar/energy/service.py`, `src/sonar/web/templates/index.html:105-292`, `src/sonar/web/api/cashflow.py:53-66`, `tests/cashflow/test_service.py:1-60`, `tests/web/test_dashboard_page.py:1-60`, `tests/web/test_api_dashboard.py:1-40`
Write: `src/sonar/energy/service.py`, `src/sonar/cashflow/service.py`, `src/sonar/web/templates/index.html`, `src/sonar/web/static/sonar.css`, `tests/energy/test_service.py`, `tests/cashflow/test_service.py`, `tests/web/test_dashboard_page.py`, `tests/web/test_api_dashboard.py`
Test first: a meter whose projected settlement is −120,00 € on a date inside the window makes the dashboard's
  `due` hold "Gas settlement" with 12000 and lowers `expected_cents` by 12000; today it does not, so it fails.
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow/test_service.py -k energy` passes: a negative settlement in the window
  is a due item, a positive one an inflow, one outside the window or zero changes nothing
- C2 [cmd] `uv run pytest -q tests/web/test_dashboard_page.py tests/web/test_api_dashboard.py -k energy` passes:
  `#energy-card` rows with refund/back-payment wording, date, worst case and suggested advance; no card
  without a current period; `/api/dashboard` has `energy`
- C3 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N09 visual check
Do: gate, pre-authorized (D13). Start the app per config `visual_recipe` on a temp DB (import the newest sample,
  set salary day and balance), then run a scratch loader from the session scratchpad that posts synthetic
  data through `/api/energy`: "Gas" with one exchange and "Electricity", about 14 months of readings each,
  one settled and one current period each with a seeded `fixed` category, current settlement dates inside
  the forecast window. Check /energy and / at desktop and 375px, light and dark (read_page first, scaled
  screenshots only where layout matters), toggling "Show values" and "Show trend" on and off.
Done when:
- C1 [visual] /energy shows per meter the status stats, one chart with usage columns and a cost line, the
  readings, exchanges and periods sections and their forms, with no horizontal scroll at 375px
- C2 [visual] "Show values" shows and hides the value labels and "Show trend" the two trend lines, legible
  in light and dark, at desktop and 375px
- C3 [visual] the dashboard shows the Energy card after Installments and loans with each meter's refund or
  back-payment, date, worst case and suggested advance, and the settlement in the due list or income card
- C4 [visual] an invalid reading shows the inline error with the entered value kept

## N10 plan acceptance
Do: Check the whole plan against verify, SPEC §11 and §12 and the Energy bullet.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o src/sonar/web/static/sonar.css --minify && git diff --exit-code src/sonar/web/static/sonar.css`
- C3 [cmd] `! grep -rnE "float|date\.today|datetime\.now" src/sonar/energy`
- C4 [review] SPEC §11 checklist still holds and SPEC §12 UI acceptance holds for /energy and the dashboard
  (extends base.html, component macros, no inline `<style>`, 400 inline errors keeping values, `eur` for
  amounts, `money` for prefills)
- C5 [review] the SPEC §13 Energy bullet matches the code: units, exchanges, months, status and projection,
  chart toggles, page, API routes and the dashboard/forecast entry
- C6 [smoke] `uv run sonar` on a temp DB without the Tailwind binary or network answers 200 on /, /energy and
  /api/energy

## Log

### N01 try 1 · 2026-10-15
check: FAIL C3
- C3 exit 1: src/sonar/migrations/0011_debts_purpose_match.sql

### N01 replan 1 · 2026-10-15
plan: REPLANNED
- cause: enable-banking-daily-sync added migrations 0012_bank_connection and 0013_bank_merge, so C3 (0012 free) failed
- N01 C3 now checks 0013 is latest and 0014 is free
- energy migration renumbered to 0014 in Intent, D1 and N03 (file, test_0014, applies on a DB at 0013, reads 0013_bank_merge.sql)
- N02 SPEC citation moved to end of section 13, SPEC.md:260

### N01 try 1 · 2026-10-15
check: PASS 4/4

### N02 try 1 · 2026-10-15
exec: DONE · 1550 passed
- Added sonar.energy model.py (Meter, Reading, Exchange, BillingPeriod, FieldError, check_period/check_periods) and usage.py (continuous_series, check_series, daily_usage), plus tests and the SPEC §13 Energy bullet
- Date fields are reading_date/exchange_date (a field named date would shadow the type); series are list[tuple[date, int]] in milli; daily_usage returns Fractions in meter units (milli/1000)
check: PASS 3/3
verify: PASS

### N03 try 1 · 2026-10-15
exec: DONE · 1588 passed
- 0014_energy.sql (4 tables), energy/store.py with Stored[T](id, item) wrappers; writes re-check series/periods in the transaction and roll back on FieldError
- unique-date IntegrityError mapped to FieldError date, duplicate meter name to FieldError name; category by LEFT JOIN

### N04 try 1 · 2026-10-15
exec: DONE · 1588 passed
- energy/settlement.py: daily_kwh, cost, month_figures, current_period, meter_status, MeterStatus; 22 tests
- Choices: last year's rate is the mean daily kWh of the same days (needs a period each day); suggested advance unclamped; as_of capped at settlement+1; advance day clamped to month length

### N03 try 1 · 2026-10-15
check: PASS 3/3

### N04 try 1 · 2026-10-15
check: PASS 3/3
verify: PASS
