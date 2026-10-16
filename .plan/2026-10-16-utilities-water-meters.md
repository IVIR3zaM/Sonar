# Utilities with water meters
status: RUNNING
created: 2026-10-16 · updated: 2026-10-16
goal: Energy becomes Utilities and gains water meters with drinking and wastewater charges, a per-period advance mode (flexible or supplier schedule) and a settlement debit date, shown on /utilities and the dashboard and counted once in the payday forecast.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: The owner sees, for water as for gas and electricity, what the end of each billing cycle will cost at the current pace: the refund or back-payment and the day it is debited. A water bill has two charges on the same metered volume, drinking water and wastewater, each with its own net price, yearly base fee and VAT, so the page shows both and the total. Some suppliers fix the advance dates on the bill, so a period can follow that schedule instead of guessing an advance day. The payday forecast then contains the scheduled advances and the settlement on the day the money actually moves, never twice.

In scope: renaming the Energy feature to Utilities (package, pages, API, templates, dashboard card and key, SPEC wording) with redirects from the old page paths; migration 0016 moving the stored data to `utility_*` tables; the `water` kind in m³ with expected yearly usage; the two water charges and their gross cost per charge and in total; advance mode per period for every kind; a settlement debit offset per period; forecast items for scheduled advances and for settlements on their debit date; forms, meter page, dashboard card and JSON API for all of it; one new SPEC §13 bullet.

Out of scope: loading the owner's real bill, readings or schedule into any database (done later through the API, never in tracked files); deploying; cesspit emptying fees; a separate garden-water meter; any change to how gas and electricity are priced; categories and rules.

Constraints: AGENTS.md: strict TDD, KISS, functional core with `today` a parameter, exact `Fraction` math rounded half up once per shown figure, integer cents, no float, append-only migrations with every hand-entered energy row surviving, page routes in `web/pages/utilities.py`, page tests on ids and `data-*` via `tests/html.py`, no inline `<style>`, `sonar.css` rebuilt and committed, anonymized fixtures with no real names, IBANs or customer numbers, `tests/test_architecture.py` green. Decisions D1-D13.

Definition of done: verify passes; the SPEC §13 Utilities bullet states the rename, water, charges, advance modes, debit timing and forecast rules; /utilities shows a water meter with per-charge and total projected cost, paid so far, remaining scheduled advances and the expected settlement with its debit date; gas and electricity figures are unchanged; the dashboard card and the payday forecast include water advances and settlements without double counting; the visual gate passes at desktop and 375px, light and dark; the final check passes SPEC §11 and §12.

## Decisions

- D1 Names: package `src/sonar/utilities/` (same modules), `web/pages/utilities.py`, `web/api/utilities.py`, templates `utilities.html`, `utilities_meter.html`, `components/utility_forms.html`, chart macro `utility_chart` with `data-utility-chart` and localStorage prefix `utility-chart:` (saved toggles reset once), tests in `tests/utilities/` and `tests/web/test_utilities_page.py`, `test_utilities_meter_page.py`, `test_api_utilities.py`; `load_energy` → `load_utilities`, `EnergyNotFound` → `UtilityNotFound`; nav "Utilities" in Energy's slot with the same icon; dashboard card "Utilities" with ids `utilities-card` and `utilities`; `Dashboard.utilities` and `/api/dashboard` key `utilities` | confirmed
- D2 Old paths: GET `/energy` and GET `/energy/meters/{id}` answer 301 to `/utilities` and `/utilities/meters/{id}`; old POST routes and `/api/energy/...` are removed (404) | confirmed
- D3 Storage: `0016_utilities.sql` creates `utility_meters` (kind CHECK gas, electricity, water), `utility_readings`, `utility_exchanges`, `utility_periods` and `utility_advance_dates (id, period_id, due_date, UNIQUE (period_id, due_date))`, copies every row with its id, then drops the `energy_*` tables; a rebuild is needed anyway because SQLite cannot alter the kind CHECK and `unit_price_micro`, `base_fee_cents` become nullable; `expected_kwh` becomes `expected_usage`; new period columns `advance_mode TEXT NOT NULL DEFAULT 'flexible'`, `settlement_debit_days INTEGER NOT NULL DEFAULT 0`, `drinking_price_micro`, `drinking_base_fee_cents`, `drinking_vat_percent`, `wastewater_price_micro`, `wastewater_base_fee_cents`, `wastewater_vat_percent` (nullable); applied migrations untouched | confirmed
- D4 Water kind: `water`, unit m³, priced per m³ as is (state factor and calorific value must be empty); readings, exchanges, chart, seasonal projection and worst case as for electricity, labelled m³; the yearly expectation is renamed `expected_usage` (kWh for gas and electricity, m³ for water) in model, API, form and period list | confirmed
- D5 Water charges: `Charge(unit_price_micro, base_fee_cents, vat_percent)` = net µ€ per m³ (> 0), net base fee per year in cents (>= 0), VAT in whole percent 0-100; a water period has `drinking` and `wastewater` (both required) and null `unit_price_micro` and `base_fee_cents`; gas and electricity keep their fields and must have both charges null; API objects `{unit_price_micro, base_fee_cents, vat_percent}` or null; forms per charge "Price (ct/m³, net)" up to 4 decimals, "Base fee per year (€, net)", "VAT (%)" | confirmed
- D6 Water cost (owner: reuse the base-fee months rule, not the bill's days ÷ 360): per day and charge (m³ × net price + the day's share of the monthly base fee) × (100 + VAT) ÷ 100, where the monthly fee = yearly fee ÷ 12 and a day's share = monthly fee ÷ days in its calendar month (the gas/electricity months rule, so a full calendar month is 1 × yearly ÷ 12); total = both charges; cost so far, projected and worst case per charge and in total, gross, each rounded half up once from its own exact value (charges may differ from the total by a cent). Pins (invented): period 2026-01-01..2026-12-31, drinking 1 140 000 µ€, 3600 ct/yr, 7 %; wastewater 3 690 000 µ€, 9600 ct/yr, 0 %; expected 150 m³; readings 238.000 m³ 2025-05-31, 355.000 2025-12-31, 516.000 2026-10-16; previous period 2025-05-31..2025-12-31 with the same charges; today 2026-10-16 → so far drinking 22615, wastewater 66791, total 89406; projected 28608, 84489, 113097; worst total 113097 | confirmed
- D7 Advance mode per period, every kind: `flexible` (default, today's rules) or `schedule`; schedule needs at least one date, unique, each within start date .. settlement date + 14 days, and the advance field is the amount per scheduled advance; flexible has no dates; paid so far uses the same paid window and settled-amount exclusion in both modes; schedule: advance count = number of dates, remaining = the dates after today with no counted debit booked within 7 days before or after, × the advance, suggested advance none, the card says "Set by the supplier"; pin: the D6 water period with 24000 ct on 04-15, 06-15, 08-15, 10-15, 12-15, debits −24000 on the first four and −35330 on 2026-02-24 (previous period settled −35330) → paid 96000, 1 remaining (2026-12-15) 24000, settlement +6903; form: select "Advances" (Flexible, Supplier schedule) and a text field "Scheduled advance dates" taking YYYY-MM-DD dates separated by commas or spaces; API `advance_mode`, `advance_dates` (ISO list) | confirmed
- D8 Debit timing: `settlement_debit_days` 0-365 per period, default 0; debit date = settlement date + days (pin: 2026-12-31 + 55 = 2027-02-24); "Start new period" copies mode, charges, debit days and expected usage and moves scheduled dates one year later | confirmed
- D9 Forecast: per meter, the current period's projected settlement and the latest period that ended before the estimate date (its settled amount when entered, else its projected settlement as of its own settlement date) each add "<meter> settlement" on their debit date when it is inside [estimate date + 1, payday − 1], a due item when negative and an inflow when positive (overrides the SPEC rule that a settled amount has no effect on any forecast); each remaining scheduled advance of a schedule-mode current period dated in the window adds the due item "<meter> advance", unless a recurring payment not linked to a debt with that period's category has a due item in the window; flexible advances stay recurring payments | confirmed
- D10 Dashboard: the Utilities card lists every meter with a current period, water included: refund or back-payment with the debit date, worst case, and the suggested advance (flexible) or "Set by the supplier" with the remaining scheduled advances (schedule); `/api/dashboard` `utilities` items add `debit_date`, `advance_mode`, `remaining_advance_dates`, `remaining_advances_cents` | confirmed
- D11 Utilities page: a water card shows cost so far and projected per charge (Drinking water, Wastewater) and in total; every card shows paid so far, remaining advances (schedule: count, amount and next date), the expected settlement with its debit date and the worst case; the meter page's period list and form cover charges, mode, scheduled dates and debit days; readings table and chart say m³ per day and m³ for water | confirmed
- D12 Visual gate, pre-authorized: config `visual_recipe` on a temp DB, balance 2026-10-16 and salary day 1 (window 2026-10-17..2026-10-31), plus a loader in the session scratchpad (never the repo) that creates `fixed` categories "Water" and "Gas", imports a synthetic Deutsche Bank CSV shaped like `tests/fixtures/db_girokonto.csv` with neutral counterparties, adds counterparty rules and posts through `/api/utilities`: Water as D6 but scheduled 24000 on 2026-04-25, 06-25, 08-25, 10-25, 12-25, debit days 55 on both periods, debits −240,00 on 04-25, 06-25, 08-25 and −353,30 on 2026-02-24; Gas flexible, periods 2025-09-01..2026-08-31 settled −45,00 with debit days 55 (debit 2026-10-25) and 2026-09-01..2027-08-31 (9,38 ct/kWh, 15,95 €/month, factors 0,9653/11,5, advance 180 €, 15000 kWh), debits −180,00 on the 2nd 2025-09-02..2026-10-02, readings 2025-09-01..2026-10-10 | confirmed
- D13 Loading the owner's real water bill and readings, and deploying, happen after the plan, by the orchestrator through the API | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/- | 1 | 0 | DONE | |
| N02 | SPEC Utilities bullet | exec | N01 | sonnet/sonnet | 1 | 0 | DONE | |
| N03 | rename Energy to Utilities | exec | N01 | sonnet/sonnet | 1 | 1 | RUNNING | |
| N04 | utility tables and period model | exec | N03 | sonnet/sonnet | 0 | 0 | TODO | |
| N05 | water cost and advance modes | exec | N04 | opus/sonnet | 0 | 0 | TODO | |
| N06 | forecast and dashboard card | exec | N05 | sonnet/sonnet | 0 | 0 | TODO | |
| N07 | utilities API | exec | N05 | sonnet/sonnet | 0 | 0 | TODO | |
| N08 | utilities pages | exec | N06 | sonnet/sonnet | 0 | 0 | TODO | |
| N09 | visual check | gate | N07,N08 | -/- | 0 | 0 | TODO | |
| N10 | plan acceptance | check | N02,N09 | -/sonnet | 0 | 0 | TODO | |

## N01 preflight
Do: Confirm the starting point: verify passes on the untouched tree, the Tailwind CLI builds (the only
  download), 0015 is the latest migration so 0016 is free, `samples/` holds a file for the gate, and the repo
  is writable. Tests need no network. A dirty tree (`.gitignore`, `.claude/launch.json`, this plan) is fine.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-preflight.css" --minify`
  exits 0 and writes outside the repo
- C3 [cmd] `ls src/sonar/migrations/0015_*.sql && test -z "$(ls src/sonar/migrations/0016_* 2>/dev/null)"`
- C4 [cmd] `test -n "$(ls samples/ 2>/dev/null)"`
- C5 [cmd] `test -w .git/index && git status --porcelain >/dev/null`

## N02 SPEC Utilities bullet
Do: Add one SPEC §13 bullet "Utilities (§13 Energy, Energy billing cycle; renames and extends them)" after
  SPEC.md:262, in SPEC's terse style, stating every rule R1-R10 below and nothing else; change no other line.
Context: the rules (D1-D11):
  R1 Rename: Energy is now Utilities: `/utilities` (nav "Utilities"), `/utilities/meters/{id}`, `/api/utilities/...`,
  card "Utilities", `/api/dashboard` key `utilities`; GET `/energy` and `/energy/meters/{id}` answer 301 to them;
  `/api/energy` is gone; migration 0016 moves all stored meters, readings, exchanges, periods to `utility_*`.
  R2 Water: kind `water`, unit m³, no state factor or calorific value; readings, exchanges, chart, seasonal
  projection and worst case as for electricity, in m³; expected kWh becomes `expected_usage` per year (kWh, m³).
  R3 Charges: a water period has no unit price or base fee but two charges as on the bill, Drinking water
  (`drinking`) and Wastewater (`wastewater`): net price per m³ (µ€; forms ct/m³, up to 4 decimals), net base fee
  per year (cents; forms €), VAT in whole percent 0-100; required for water, empty otherwise.
  R4 Water cost per day and charge = (m³ × net price + yearly base fee ÷ 12 ÷ days in that month) × (100 + VAT)
  ÷ 100 (the base-fee months rule), total = both; so far, projected and worst case per charge and in total,
  gross, each rounded half up once from its exact value.
  R5 Advance mode per period, any kind: `flexible` (default; Energy billing cycle rules) or `schedule`: the
  supplier's dates (`advance_dates`: at least one, unique, each from start date to settlement date + 14 days),
  the advance being the amount per date; flexible has no dates. Schedule: paid so far as flexible; advance count
  = number of dates; remaining = dates after today with no counted debit within 7 days of them, × the advance;
  no suggested advance, the card says "Set by the supplier".
  R6 Debit: `settlement_debit_days` 0-365 (default 0); debit date = settlement date + days; "Start new period"
  copies mode, charges, debit days and expected usage and moves scheduled dates one year later.
  R7 Forecast (overrides the Energy bullet's settlement-date rule and the billing cycle bullet's "no effect on
  any forecast"): per meter the current period's projected settlement and the latest period ended before the
  estimate date (settled amount when entered, else its projection as of its settlement date) add "<meter>
  settlement" on their debit date inside the window (due if negative, inflow if positive); each remaining
  scheduled advance in the window adds due "<meter> advance" unless a recurring payment (not linked to a debt)
  in that period's category is due in the window; flexible advances stay recurring payments.
  R8 Card: every meter with a current period: settlement with debit date, worst case, suggested advance
  (flexible) or "Set by the supplier" with the remaining scheduled advances. R9 Page: water cards show so far and
  projected per charge and in total; every card shows paid so far, remaining advances (schedule: count, amount,
  next date), settlement with debit date, worst case.
  R10 API: periods carry `expected_usage`, `advance_mode`, `advance_dates`, `settlement_debit_days`, `drinking`,
  `wastewater` (`{unit_price_micro, base_fee_cents, vat_percent}` or null; water has null `unit_price_micro`,
  `base_fee_cents`); status adds `charges`, `advance_mode`, `remaining_advance_dates`, `debit_date`.
Write: `SPEC.md`
Done when:
- C1 [review] `git diff SPEC.md` adds exactly one bullet after the Energy billing cycle bullet, changes no line,
  and states each of R1-R10 with the numbers, defaults and names given, contradicting none
- C2 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N03 rename Energy to Utilities
Do: Rename the Energy feature to Utilities with no change in behavior (D1, D2). `git mv` the package, the page
  and API modules, the templates and the tests to the D1 names and update every import, route, template name,
  hook and label; pages move to `/utilities` and `/utilities/meters/{id}` (forms post there), the API to
  `/api/utilities/...`; add GET `/energy` and GET `/energy/meters/{id}` answering 301 to the new paths. Rename
  the period field `expected_kwh` to `expected_usage` in the model, API, form and period list (the store keeps
  mapping it to the `energy_periods.expected_kwh` column; tables stay `energy_*` until N04). `Dashboard.energy`
  becomes `utilities`, so `/api/dashboard` answers `utilities`; the card becomes "Utilities"
  (`templates/index.html:291-322`). Rename the form hint needle to `expected_usage must not be negative`
  (`web/forms.py:60`) so that error keeps its friendly text. Rebuild sonar.css.
Context: D1 names; D2 old paths (301; no `/api/energy` alias). Wiring: `src/sonar/web/app.py:36,136`,
  `web/api/__init__.py:19,25`, nav `templates/base.html:11,28`, `cashflow/service.py:35,72-74,137,161,176`,
  chart macro `components/charts.html:183-260`, toggle script `templates/energy.html:121-130`, page routes
  `web/pages/energy.py:364-480`, not-found text `pages/energy.py:298-301`. Migration tests 0014 and 0015 stay.
Read: `src/sonar/energy/`, `src/sonar/web/pages/energy.py`, `src/sonar/web/api/energy.py`, `tests/html.py`
Write: `src/sonar/energy/**`, `src/sonar/utilities/**`, `src/sonar/web/pages/energy.py`, `src/sonar/web/pages/utilities.py`, `src/sonar/web/api/energy.py`, `src/sonar/web/api/utilities.py`, `src/sonar/web/api/__init__.py`, `src/sonar/web/app.py`, `src/sonar/web/forms.py`, `src/sonar/web/templates/**`, `src/sonar/web/static/sonar.css`, `src/sonar/cashflow/service.py`, `tests/energy/**`, `tests/utilities/**`, `tests/web/**`, `tests/cashflow/**`
Test first: GET /energy → 301 Location /utilities; GET /energy/meters/7 → 301 /utilities/meters/7; GET
  /api/energy → 404 and /api/utilities lists meters; /api/dashboard has `utilities` and no `energy`; the nav
  item "Utilities" is current on /utilities; a period item has `expected_usage`; a period form with a negative
  expected usage shows "Expected usage must not be negative.".
Done when:
- C1 [cmd] `test ! -e src/sonar/energy && ! grep -rnE "sonar\.energy|load_energy|EnergyNotFound|energy_chart|data-energy|energy-chart" src tests`
- C2 [review] the only `/energy` routes left are the two GET redirects in `web/pages/utilities.py`, answering
  301; every other page route is under `/utilities` and every API route under `/api/utilities`
- C3 [review] labels and hooks follow D1: nav "Utilities", page heading "Utilities", card "Utilities" with ids
  `utilities-card` and `utilities`, `utility_chart` with `data-utility-chart` and key prefix `utility-chart:`,
  404 text "No such utility record", form label "Expected usage per year", and the `web/forms.py`
  hint keyed on `expected_usage must not be negative`
- C4 [review] behavior unchanged: the test diff renames paths, names, hooks and the `expected_usage` and
  `utilities` keys only; no asserted figure changes
- C5 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/n03.css" --minify && cmp "$TMPDIR/n03.css" src/sonar/web/static/sonar.css`
- C6 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N04 utility tables and period model
Do: Add migration `0016_utilities.sql` (D3) and point the store at the `utility_*` tables. Extend the model:
  kind `water` (D4); `Charge` and the period fields `drinking`, `wastewater`, `advance_mode`, `advance_dates`,
  `settlement_debit_days` with defaults so existing callers keep working; `unit_price_micro` and
  `base_fee_cents` become optional. Validation in `check_period` (FieldError naming the field): gas and
  electricity need `unit_price_micro` > 0 and `base_fee_cents` >= 0 and no charges; water needs both charges
  (price > 0, base fee >= 0, VAT 0-100) and null unit price, base fee, state factor and calorific value; mode
  is `flexible` or `schedule`; schedule needs >= 1 unique date within start .. settlement + 14 days; flexible
  has none; debit days 0-365. The store writes a period's dates in `utility_advance_dates` inside the same
  transaction (update replaces them, delete removes them) and reads them sorted.
Context: D3 schema and copy-with-ids; D4 `water`; D5 charge fields and limits; D7 mode and date rules; D8 debit
  days. Model `src/sonar/utilities/model.py:13,51-78`; store `store.py:24-29,179-235,252-270`; SQLite rebuild
  pattern: create new tables, `INSERT ... SELECT` with ids, drop the old ones; foreign keys are off.
Read: `src/sonar/migrations/0014_energy.sql`, `src/sonar/migrations/0015_energy_settled.sql`, `tests/migrations/test_0015.py`, `src/sonar/db.py:26-69`
Write: `src/sonar/migrations/0016_utilities.sql`, `src/sonar/utilities/model.py`, `src/sonar/utilities/store.py`, `tests/migrations/test_0016.py`, `tests/utilities/test_model.py`, `tests/utilities/test_store.py`, `tests/web/test_api_utilities.py`
Test first: a DB migrated to 0015 holding a gas meter, a reading, an exchange and two periods (one settled)
  keeps every id and value after 0016 (`expected_kwh` in `expected_usage`), with mode `flexible`, debit days 0,
  null charges, and no `energy_*` table left; `kind = 'water'` inserts and `'oil'` fails; each validation rule
  above raises FieldError with its field; a schedule period round-trips its dates through the store.
Done when:
- C1 [cmd] `uv run pytest -q tests/migrations/test_0016.py tests/utilities/test_model.py tests/utilities/test_store.py`
- C2 [cmd] `git diff --quiet HEAD -- src/sonar/migrations/0001_import.sql src/sonar/migrations/0014_energy.sql src/sonar/migrations/0015_energy_settled.sql`
- C3 [review] 0016 copies all four tables with their ids, drops `energy_*`, and its test pins each copied
  column; the store names only `utility_*` tables
- C4 [review] every validation rule of Do has a failing-then-passing test; gas and electricity periods valid
  before stay valid; `tests/web/test_api_utilities.py` changes only to expect the new default keys
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N05 water cost and advance modes
Do: In `utilities/settlement.py`, price each day by its period: water by the two charges with the base-fee months
  rule on yearly ÷ 12 and VAT (D6), gas and electricity as today. `MeterStatus` gains `charges` (per charge: name, cost so
  far, projected cost; empty for gas and electricity and without a projection), `advance_mode`,
  `remaining_advance_dates` (schedule only) and `debit_date` (D8). Schedule mode (D7): advance count = number of
  dates, remaining = dates after `today` with no counted debit booked within 7 days of them, suggested advance
  None; flexible keeps today's rules. Chart month costs for water use the gross total.
Context: D6 formula and pins; D7 schedule rules and pin (paid 96000, remaining 24000 on 2026-12-15, settlement
  +6903); D8 debit date (2026-12-31 + 55 days = 2027-02-24). Code: `MeterStatus` `settlement.py:46-59`,
  `meter_status` `:202-261`, `_kwh_per_unit` `:334-338`, `_fee_per_day` `:351-352`, `_exact_cost` `:355-363`,
  `_energy_cents` `:366-367`, `_rest_cost` `:370-375`, `_paid_advances` `:396-410`, `_advance_count`
  `:413-422`, `_advances_due` `:425-439`; service `utilities/service.py:45-66`.
Read: `src/sonar/utilities/settlement.py`, `src/sonar/utilities/model.py`, `tests/utilities/test_settlement.py`
Write: `src/sonar/utilities/settlement.py`, `src/sonar/utilities/service.py`, `tests/utilities/test_settlement.py`, `tests/utilities/test_service.py`, `tests/web/test_api_utilities.py`
Test first: the D6 water example as of 2026-10-16 gives so far 22615 / 66791 / 89406 and projected 28608 /
  84489 / 113097 and worst total 113097; with the D7 schedule and debits, paid 96000, remaining dates
  (2026-12-15,), remaining 24000, settlement 6903, suggested None, advance count 5; debit date 2027-02-24 with
  55 days.
Done when:
- C1 [cmd] `uv run pytest -q tests/utilities/test_settlement.py tests/utilities/test_service.py`
- C2 [review] tests pin every D6 and D7 figure above, plus: a debit 3 days before a scheduled date covers it;
  a debit 8 days away does not; a date on or before today is never remaining
- C3 [review] every pre-existing gas and electricity settlement test keeps its figures; a flexible period has
  empty `charges` and `remaining_advance_dates`, and debit date = settlement date with 0 days
- C4 [review] pure and exact: no `date.today`, no float; each shown figure is rounded once from its exact value
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N06 forecast and dashboard card
Do: Make the payday forecast and the dashboard card follow D9 and D10. `SettlementSummary` gains the debit
  date, advance mode, remaining scheduled dates and their cents; the utilities service also yields, per meter,
  the latest period ended before the estimate date (settled amount, else its projection as of its settlement
  date) and the schedule-mode advances still due. `load_dashboard` places settlements on their debit date
  inside the window and adds "<meter> advance" due items, skipping a meter whose period category has a due
  item from a recurring payment not linked to a debt (`RecurringPayment.category`). The card shows the debit
  date and, for schedule meters, "Set by the supplier" with the remaining count instead of the suggested
  advance. Rebuild sonar.css.
Context: D9 rules; D10 card and keys. Code: `utilities/service.py:80-109`, `cashflow/service.py:137,176-187,
  293-301,324-340`, `recurring/store.py:34-45`, card `templates/index.html:291-322`. Window = [estimate date +
  1, payday − 1]; flexible meters with debit days 0 must behave exactly as before.
Read: `src/sonar/cashflow/service.py`, `src/sonar/utilities/service.py`, `tests/cashflow/test_service.py:842-910`
Write: `src/sonar/utilities/service.py`, `src/sonar/cashflow/service.py`, `src/sonar/web/templates/index.html`, `src/sonar/web/static/sonar.css`, `tests/utilities/test_service.py`, `tests/cashflow/test_service.py`, `tests/web/test_dashboard_page.py`, `tests/web/test_api_dashboard.py`
Test first: a schedule date inside the window becomes due "Water advance" for the advance; with a recurring
  payment of the Water category due in the window it does not, and the recurring item stays; an ended period
  with settled −35330 and debit days 55 adds due "Water settlement" 35330 on its debit date in the window.
Done when:
- C1 [cmd] `uv run pytest -q tests/cashflow/test_service.py tests/utilities/test_service.py tests/web/test_dashboard_page.py tests/web/test_api_dashboard.py`
- C2 [review] tests cover: scheduled date in, outside, and covered by a recurring payment; flexible adds no
  advance item; current settlement on its debit date (in and out of the window); ended period with and
  without a settled amount; debit date on or before the estimate date adds nothing
- C3 [review] the card shows the debit date (`data-field="date"`) and, for schedule meters,
  `data-field="advances"` with "Set by the supplier" instead of `suggested-advance`; a water meter is listed;
  `/api/dashboard` `utilities` items carry the D10 keys
- C4 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/n06.css" --minify && cmp "$TMPDIR/n06.css" src/sonar/web/static/sonar.css`
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N07 utilities API
Do: Extend `web/api/utilities.py` so meters of kind `water` and periods with every new field are created,
  read, updated and deleted with the model's own validation (API parity): `PeriodIn` takes `expected_usage`,
  optional `unit_price_micro` and `base_fee_cents`, `advance_mode` (default `flexible`), `advance_dates` (ISO
  strings, default empty), `settlement_debit_days` (default 0), `drinking` and `wastewater` (strict objects
  `{unit_price_micro, base_fee_cents, vat_percent}` or null). Period items and the meter status come back in
  stored units with ISO dates, including `charges`, `remaining_advance_dates` and `debit_date`.
Context: D5 charge fields; D7 mode and dates; D8 debit days; errors as today: 400 `{error, field}` for a
  FieldError or a bad ISO date, 404 unknown id, 409 deleting a non-empty meter, 422 unknown key or wrong JSON
  type, 201 on create. Code: `PeriodIn` `api/utilities.py:62-73`, `_period` `:91-103`, `_period_item` `:124-125`,
  `_meter_item` `:128-137`, `_StrictModel` and `_jsonable` in `api/_common.py:52-62`.
Read: `src/sonar/web/api/utilities.py`, `src/sonar/web/api/_common.py`, `tests/web/test_api_utilities.py`
Write: `src/sonar/web/api/utilities.py`, `tests/web/test_api_utilities.py`
Test first: POST a water meter, POST the D6 period with the D7 schedule and 55 debit days → 201 and the item
  echoes every field; GET /api/utilities as of 2026-10-16 shows status charges, remaining dates and debit date.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_api_utilities.py`
- C2 [review] tests pin 400 with its field for: water without `drinking`, gas with a charge, VAT 101,
  schedule without dates, flexible with dates, a date outside the period, a duplicate date, `"2026-13-01"` in
  `advance_dates`, debit days −1; 422 for an unknown key inside a charge and for `advance_dates` as a string
- C3 [review] PUT replaces a period's dates and charges; DELETE removes them; 404 for unknown meter or period
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N08 utilities pages
Do: Bring the pages to D11. Add meter offers `water`. The meter page's period form shows by meter kind: gas and
  electricity keep today's fields; water shows Drinking water and Wastewater groups (D5 labels) instead of unit
  price, base fee, state factor and calorific value; every kind gets "Advances" (Flexible, Supplier schedule),
  "Scheduled advance dates" and "Settlement debited (days after)". The period list shows them; "Start new
  period" prefills per D8. Each /utilities card shows paid so far, remaining advances (schedule: count, amount,
  next date), expected settlement with its debit date and worst case; a water card adds per-charge and total
  cost so far and projected; schedule cards say "Set by the supplier" instead of the suggested advance. Units
  per kind (`UNITS`, `pages/utilities.py:58`) label the readings table and chart (m³ for water). Rebuild css.
Context: D5 form labels and scales (ct/m³ to µ€ like `_period_from` `pages/utilities.py:112-129`), D7 date
  field syntax, D8 prefill (`_one_year_later` `:169`, `_next_period_values` `:176`), D11 contents. Invalid input
  re-renders 400 with the inline error and the entered values (SPEC §12); hooks: `data-charge="drinking"`,
  `data-charge="wastewater"`, `data-field` per stat.
Read: `src/sonar/web/pages/utilities.py`, `src/sonar/web/templates/utilities.html`, `src/sonar/web/templates/utilities_meter.html`, `src/sonar/web/templates/components/utility_forms.html`, `tests/html.py`
Write: `src/sonar/web/pages/utilities.py`, `src/sonar/web/templates/utilities.html`, `src/sonar/web/templates/utilities_meter.html`, `src/sonar/web/templates/components/utility_forms.html`, `src/sonar/web/templates/components/charts.html`, `src/sonar/web/forms.py`, `src/sonar/web/static/sonar.css`, `tests/web/test_utilities_page.py`, `tests/web/test_utilities_meter_page.py`, `tests/web/test_charts.py`, `tests/web/test_forms.py`
Test first: as of 2026-10-16 the D6/D7 water card shows drinking 226,15 € / 286,08 €, wastewater 667,91 € /
  844,89 €, total 894,06 € / 1.130,97 €, paid 960,00 €, 1 advance left 240,00 € on 15.12.2026, refund 69,03 €
  debited 24.02.2027 and "Set by the supplier".
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_utilities_page.py tests/web/test_utilities_meter_page.py tests/web/test_charts.py tests/web/test_forms.py`
- C2 [review] the water period form creates and edits the D6/D7 period; gas and electricity forms keep their
  fields and add mode, dates and debit days; 400 re-renders keep values for a bad date, a missing charge, VAT 101
- C3 [review] the water card pins the Test first figures by hooks; a flexible gas card still shows the
  suggested advance; readings table and chart say m³ for water and kWh for electricity
- C4 [review] Start new period copies mode, charges, debit days and expected usage and moves dates a year later
- C5 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/n08.css" --minify && cmp "$TMPDIR/n08.css" src/sonar/web/static/sonar.css`
- C6 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N09 visual check
Do: gate, pre-authorized (D12). Start the app per config `visual_recipe` on a temp DB, set balance 2026-10-16
  and salary day 1, run the D12 scratchpad loader (categories, synthetic CSV, rules, Water and Gas meters
  through `/api/utilities`), then check /, /utilities and both meter pages at desktop and 375px, light and dark
  (read_page first, scaled screenshots only where layout matters). Values below assume today 2026-10-16..24.
Done when:
- C1 [visual] /energy lands on /utilities; nav "Utilities" is current; no page says "Energy"
- C2 [visual] the Water card shows Drinking water, Wastewater and Total for cost so far and projected
  (projected total 1.130,97 €), paid 720,00 €, 2 advances left (480,00 €, next 25.10.2026), refund 69,03 €
  debited 24.02.2027 and "Set by the supplier"; its chart and readings say m³
- C3 [visual] the Gas card still shows its suggested advance, worst case and kWh chart
- C4 [visual] the Water meter page lists both periods with charges, mode, scheduled dates and debit days; the
  period form shows the water charge groups and keeps entered values on an invalid VAT
- C5 [visual] the dashboard Utilities card lists Water and Gas with debit dates; the due list holds exactly one
  water advance item around 25.10.2026 and "Gas settlement" 45,00 € on 25.10.2026
- C6 [visual] nothing wraps badly, clips or scrolls sideways at 375px, in light and dark

## N10 plan acceptance
Do: Check the whole plan against verify, SPEC §11 and §12 and the new SPEC §13 Utilities bullet.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/n10.css" --minify && cmp "$TMPDIR/n10.css" src/sonar/web/static/sonar.css`
- C3 [cmd] `! grep -rnE "float|date\.today|datetime\.now" src/sonar/utilities`
- C4 [cmd] `git diff --quiet 45526fa -- src/sonar/migrations/0014_energy.sql src/sonar/migrations/0015_energy_settled.sql`
- C5 [review] SPEC §11 checklist holds and SPEC §12 UI acceptance holds for /utilities, the meter page and the
  dashboard card (base.html, component macros, no inline `<style>`, 400 inline errors keeping values, `eur`
  amounts, `money` prefills, usable without script)
- C6 [review] the SPEC §13 Utilities bullet matches the code: rename and redirects, water and charges, base-fee
  months rule on yearly ÷ 12 with VAT, advance modes, debit days, forecast items without double counting, card, API keys
- C7 [review] no tracked file holds a real name, IBAN or customer number; fixtures are invented
- C8 [smoke] `uv run sonar` on a temp DB answers 200 on /, /utilities and /api/utilities, 301 on /energy, and
  200 on /utilities/meters/<id> after `POST /api/utilities/meters` creates a water meter

## Log

### N01 try 1 · 2026-10-16
check: PASS 5/5

### N03 try 1 · 2026-10-16
exec: BLOCKED · rename done, pytest 1797 passed, ruff clean, C1 and C5 pass; forms.py hint needs one line outside Write
- src/sonar/web/forms.py:60 maps the needle 'expected_kwh must not be negative', but the model now says 'expected_usage must not be negative', so that form error shows raw text; rename the needle to expected_usage (forms.py is not in Write)

### N02 try 1 · 2026-10-16
exec: DONE · 1797 passed, ruff clean
- Appended one SPEC §13 Utilities bullet after the Energy billing cycle bullet stating R1-R10; no other line changed
- Tree was changed concurrently by other nodes during verify; transient failures there were not from SPEC.md

### N03 replan 1 · 2026-10-16
plan: REPLANNED
- cause: forms.py:60 DOMAIN_ERROR_HINTS needle expected_kwh was outside Write
- brief adds src/sonar/web/forms.py to Write, the needle rename to Do, a negative expected usage form test to Test first, and the hint to C3

### N02 try 1 · 2026-10-16
check: PASS 1/1
verify: PASS
