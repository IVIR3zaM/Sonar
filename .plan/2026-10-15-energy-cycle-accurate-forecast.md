# Energy cycle-accurate forecast
status: RUNNING
created: 2026-10-15 · updated: 2026-10-15
goal: The Energy monitor's current-period figures (paid so far, projection, worst case, suggested advance) follow how the supplier bills, with a settled amount per period, a per-meter history page, a two-cycle chart with projected months and remembered chart toggles, recorded as a SPEC §13 amendment.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: The Energy page and the dashboard should show the same numbers the supplier's bill will: advances debited just after a settlement date belong to the closed period, a period's settled back-payment or refund is recorded and never mistaken for an advance, the rest of the period is projected from last cycle's seasonal usage scaled by how this cycle compares, and the suggested advance divides the whole period's projected cost over the advances the supplier actually charges (11 per year). The Energy page itself becomes short: each meter card keeps its figures, chart, latest reading and add-reading form, while the full history (readings, exchanges, billing periods) moves to a page per meter. The chart compares the current cycle with the previous one and shows the projected rest of the current cycle, and its two toggles are remembered by the browser.

In scope: a new SPEC §13 "Energy billing cycle" bullet amending the Energy bullet (figures, page split, chart and remembered toggles); a nullable signed `settled_cents` per billing period (migration `0015_energy_settled.sql`, model, store, JSON API, period form, period list); a 14-day grace window that moves early debits to the closed period and starts the current one at settlement + 15 days ("paid since"); exclusion of the previous period's settled amount from paid; remaining advances capped by the period's advance count; the seasonal projection and its worst case; the new suggested advance; the "Last settlement" line on the current period's card; a meter page `/energy/meters/{id}` with the readings table, exchanges and billing periods; the per-cycle chart with projected months; one small inline script remembering "Show values" and "Show trend" per meter chart. The dashboard Energy card and the forecast pick the figures up through the existing service.

Out of scope: deploying to prod and entering prod data (the orchestrator does that after the plan); a new nav item (the meter page sits under "Energy"); categories and rules; new forecast items for a settled amount; any script beyond the toggle memory; the dashboard's chart and layout.

Constraints: AGENTS.md: strict TDD, KISS, pure functions with `today` a parameter, exact `Fraction` math rounded half up once per shown figure, integer cents, no float, a new migration only (hand-entered energy data survives), page routes in `web/pages/energy.py`, page tests on ids and `data-*` via `tests/html.py`, no inline `<style>`, `sonar.css` rebuilt and committed, `tests/test_architecture.py` green; the page works fully without script. Decisions D1-D15.

Definition of done: SPEC §13 amended; tests pin the 14-day grace with both bills' dates, the settled-amount exclusion, the owner's 40/50/100 → 90 seasonal example, both bills' advance checks, the cycle months of the chart and the meter page's forms; verify passes; the visual gate passes on a temp DB with prod-like synthetic data at desktop and 375px, light and dark, including the meter page, the two-cycle chart and remembered toggles; the final check passes SPEC §11 and §12.

## Decisions

- D1 Layout: a new SPEC §13 bullet "Energy billing cycle (§13 Energy; overrides its paid so far, remaining advances, projection, worst case, suggested advance, chart and page rules)" right after the Energy bullet (SPEC.md:261); migration `src/sonar/migrations/0015_energy_settled.sql`; code stays in `src/sonar/energy/`, `web/api/energy.py`, `web/pages/energy.py`, `templates/energy.html` plus `templates/energy_meter.html` and shared form macros in `templates/components/energy_forms.html`; `templates/index.html` and `cashflow/` unchanged | confirmed
- D2 Paid window: the previous period is the meter's period with the latest settlement date before this period's start; paid since = max(start_date, previous settlement_date + 15 days), else start_date; window end = min(today, settlement_date + 14 days); debits in the period's category booked in the window count, credits never; `MeterStatus` gains `paid_since`; the page's "Paid so far" reads "paid since <date>". Pins: gas 2025-09-03..2026-08-25 then 2026-08-26..: the 2026-09-02 −180,00 debit is not paid in the new period, paid since 2026-09-09; electricity 2025-07-09..2025-12-31 then 2026-01-01..: 2026-01-06 −200,00 not paid, paid since 2026-01-15 | confirmed
- D3 Settled amount: `settled_cents` nullable signed integer on a period, negative back-payment and positive refund as on the bill (the sign its bank transaction carries); form "Settled amount (€)" optional, signed, empty = none; API key `settled_cents` (int or null, default null) in POST/PUT and every period item; "Start new period" leaves it empty; the period list shows it; the current period's card shows "Last settlement: back-payment|refund X on <previous settlement date>" when the previous period has one; it adds nothing to the forecast (a past bill) | confirmed
- D4 Exclusion: a transaction in the current period's category whose `amount_cents` equals the previous period's `settled_cents` and is booked after that previous settlement date never counts as paid | confirmed
- D5 Remaining advances: advance day = day of the latest counted debit (none: the paid-since day); remaining = advance_cents × min(occurrences of that day after the latest counted debit (none: from paid since on) up to settlement_date + 14 days, max(0, advance count − counted debits)), so a 12-month period never projects more than 11 advances (gas today: 1 paid + 10 left) | confirmed
- D6 Advance count = max(1, round half up(months × 11 ÷ 12)), months = the base-fee months of the whole period (Σ covered days ÷ days in that month); 2026-08-26..2027-08-25 and 2026-01-01..2026-12-31 → 11; 2025-07-09..2025-12-31 → 5; `MeterStatus` gains `advance_count` | confirmed
- D7 Suggested advance = projected cost of the whole period ÷ advance count, rounded up to whole euros; None only without a projection. Pins at the stored exact prices: gas (15701 kWh × 93800 µ€ + 12 × 1595 ct) ÷ 11 → 15200 ct; electricity (8558 kWh × 318325 µ€ + 12 × 1041 ct) ÷ 11 = 259,01 € → 26000 ct | confirmed
- D8 Seasonal projection in meter units: ratio month = the latest calendar month fully inside the current period with every day in the daily usage before as_of; ratio = its units ÷ the units of the same month a year earlier, which must be fully covered by the series and above 0, else no ratio; each remaining day d in [as_of, settlement_date] uses units = prev(d) × (1 + ratio) ÷ 2, prev(d) = the usage on `same_day_last_year(d)`; converted to kWh with the current period's factors and priced with its price and per-day base fee; no ratio or no prev(d) → expected_kwh ÷ 365 kWh that day. Owner pin: this October 40, last October 50, last November 100 → November 90 | confirmed
- D9 Worst case: per remaining day kWh = max(seasonal(d), expected_kwh ÷ 365, prev(d) in kWh when known); the current-daily-rate term and the all-days-or-nothing last-year average go | confirmed
- D10 Visual gate, pre-authorized: config `visual_recipe` on a temp DB, plus a loader in the session scratchpad (never the repo) that creates `fixed` categories "Gas" and "Electricity", imports a synthetic Deutsche Bank CSV with neutral counterparty names, adds counterparty rules, and posts meters, readings and periods through `/api/energy`: gas 2025-09-03..2026-08-25 settled −31,69 € and 2026-08-26..2027-08-25 (9,38 ct, 15,95 €, 15701 kWh, factors 0,9653/11,5, advance 180 €), electricity 2025-07-09..2025-12-31 settled −270,13 € and 2026-01-01..2026-12-31 (31,8325 ct, 10,41 €, 8558 kWh, advance 200 €); debits gas −180 on the 2nd 2025-11-02..2026-10-02 plus −31,69 on 2026-10-05, electricity −200 on the 6th 2025-08-06..2026-10-06 plus −270,13 on 2026-01-20; readings 2025-07-01..2026-10-10, gas higher in winter | confirmed
- D11 Deploying and entering prod data happen after the plan, by the orchestrator | confirmed
- D12 Cycle months of the chart: a calendar month belongs to the period in force on its 1st; current cycle = the current period (none: the latest period, with no projected months); previous cycle = the meter's period with the latest settlement before the current cycle's start; actual months = the cycle's months in the month figures (SPEC §13 Energy day allocation); projected months = the current cycle's months after its last actual month through the settlement month, each summing measured days before as_of and seasonal days (D8) from as_of through min(month end, settlement date), priced by the current period; past 24 months the oldest previous months drop; trend lines fit the actual months only (gas: Oct 2025-Aug 2026 previous, Sep 2026 actual, Oct 2026-Aug 2027 projected) | confirmed
- D13 Meter page (owner request): `/energy/meters/{id}` (404 for an unknown id; nav "Energy" stays current) holds the full readings table with edit and delete, meter exchanges and billing periods with their lists and forms, "Start new period" and the settled amount; `/energy` keeps per meter only the stats, the chart, the latest reading, the add-reading form, a "History, periods and exchanges" link and the delete-meter button, so the two cards are short and their charts sit close together; a form on the meter page redirects (303) to and re-renders its 400 on the meter page, the add-reading form on `/energy` | confirmed
- D14 Remembered toggles (owner request; amends "done without script"): one small inline script on `/energy` stores each meter chart's "Show values" and "Show trend" states in localStorage, key per chart id and toggle, restores them on load, all wrapped in try/catch; without script or storage the checkboxes still work, off by default | confirmed
- D15 Cycle chart (owner request): the current cycle plus the previous one, at most 24 months (D12): previous-cycle months in a muted color, current actual months solid, current projected months outlined or hatched with the cost line dashed over them, a legend entry for each; under 640px only the current cycle (actual + projected) shows | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/- | 0 | 0 | TODO | |
| N02 | SPEC amendment and settled amount | exec | N01 | sonnet/sonnet | 0 | 0 | TODO | |
| N03 | paid window and remaining advances | exec | N02 | sonnet/opus | 0 | 0 | TODO | |
| N04 | seasonal projection and suggested advance | exec | N03 | sonnet/opus | 0 | 0 | TODO | |
| N05 | meter page | exec | N04 | sonnet/sonnet | 0 | 0 | TODO | |
| N06 | energy card figures and settled form | exec | N05 | sonnet/sonnet | 0 | 0 | TODO | |
| N07 | cycle chart | exec | N06 | opus/opus | 0 | 0 | TODO | |
| N08 | remembered chart toggles | exec | N07 | sonnet/sonnet | 0 | 0 | TODO | |
| N09 | visual check | gate | N08 | -/- | 0 | 0 | TODO | |
| N10 | plan acceptance | check | N09 | -/sonnet | 0 | 0 | TODO | |

## N01 preflight
Do: Confirm the starting point: verify passes on the untouched tree, the Tailwind CLI builds (the only
  download), 0014 is the latest migration so 0015 is free, and the repo is writable. Tests need no network.
  A dirty working tree (`.gitignore`, `.claude/launch.json`, this plan) is fine.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-preflight.css" --minify`
  exits 0 and writes outside the repo
- C3 [cmd] `ls src/sonar/migrations/0014_*.sql && test -z "$(ls src/sonar/migrations/0015_* 2>/dev/null)"`
- C4 [cmd] `test -w .git/index && git status --porcelain >/dev/null` exits 0

## N02 SPEC amendment and settled amount
Do: Add the SPEC §13 "Energy billing cycle" bullet after the Energy bullet (SPEC.md:261), stating D2-D9 and
  D12-D15 in plain words (the meter page, the cycle chart and the remembered toggles amend the Energy
  bullet's Page and Chart sentences). Then store the settled amount: a nullable signed `settled_cents` on
  `BillingPeriod` (last field, default None), migration `0015_energy_settled.sql` adding the column, store
  read and write, and the JSON API key in POST/PUT and every period item.
Context: D1 layout, D3 settled amount (signed as on the bill; null = none; API key `settled_cents`, int or
  null, default null; a non-int is a 422 like the other keys). Model at `src/sonar/energy/model.py:52`;
  store select `src/sonar/energy/store.py:26`, add/update `store.py:183-215`; API `PeriodIn`
  `src/sonar/web/api/energy.py:63`, `_period` `:90`, `_period_item` `:122`; migration test pattern
  `tests/migrations/test_0014.py`. Existing periods read back with `settled_cents` None. No page change here.
Read: `SPEC.md` (§13 Energy bullet only), `src/sonar/energy/model.py`, `src/sonar/energy/store.py`,
  `src/sonar/web/api/energy.py`, `src/sonar/migrations/0014_energy.sql`, `tests/migrations/test_0014.py`
Write: `SPEC.md`, `src/sonar/energy/model.py`, `src/sonar/energy/store.py`, `src/sonar/web/api/energy.py`,
  `src/sonar/migrations/0015_energy_settled.sql`, `tests/migrations/test_0015.py`,
  `tests/energy/test_store.py`, `tests/web/test_api_energy.py`
Test first: a period added with `settled_cents=-3169` reads back with -3169 from `list_periods`; fails
  because the field does not exist.
Done when:
- C1 [cmd] `uv run pytest -q tests/migrations/test_0015.py tests/energy/test_store.py` passes: a period stored
  before 0015 survives with `settled_cents` None; add and update round-trip negative, positive and None
- C2 [cmd] `uv run pytest -q tests/web/test_api_energy.py -k settled` passes: POST and PUT with
  `settled_cents` -27013 answer it in the item and in `GET /api/energy`; omitted reads null; a string is 422
- C3 [review] SPEC.md has the new §13 bullet right after the Energy bullet, covering the grace window and
  paid since, the settled amount and its exclusion, remaining advances, advance count, seasonal projection,
  worst case, suggested advance, the meter page split, the cycle chart (D12, D15) and the remembered
  toggles replacing "done without script", with no real names or IBANs
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N03 paid window and remaining advances
Do: In `energy/settlement.py`, count paid so far over the period's paid window with the previous period's
  settled amount excluded, cap the remaining advances by the period's advance count, and add `paid_since`
  and `advance_count` to `MeterStatus`. `meter_status` takes the category's transactions as signed
  (booking date, amount_cents) pairs; `energy/service.py` `_advances` (`service.py:69`) passes them all.
Context: D2 paid window: previous = the period with the latest settlement before this start; paid since =
  max(start, previous settlement + 15 days); window end = min(today, settlement + 14 days); only debits
  (amount < 0) count, as positive cents. D4: a transaction whose amount equals the previous period's
  `settled_cents` and is booked after that previous settlement date never counts. D5 remaining advances:
  advance day = day of the latest counted debit (none: paid since's day); count = min(that day's
  occurrences after the latest counted debit (none: from paid since) through settlement + 14 days,
  max(0, advance_count − counted debits)). D6 advance_count = max(1, round half up(months × 11 ÷ 12)) with
  months = Σ covered days ÷ days in that month over the whole period. Leave projection, worst case and
  suggested advance as they are (N04). Current code: `meter_status` `settlement.py:112`, `_advances_due`
  `:227`. Today's pinned figures elsewhere may move: update them to the new rule, never loosen them.
Read: `src/sonar/energy/settlement.py`, `src/sonar/energy/service.py`, `src/sonar/energy/model.py`
Write: `src/sonar/energy/settlement.py`, `src/sonar/energy/service.py`, `tests/energy/test_settlement.py`,
  `tests/energy/test_service.py`, `tests/cashflow/test_service.py`, `tests/web/test_api_dashboard.py`,
  `tests/web/test_dashboard_page.py`, `tests/web/test_energy_page.py`, `tests/web/test_api_energy.py`
Test first: gas periods 2025-09-03..2026-08-25 and 2026-08-26..2027-08-25, debits 2026-09-02 −18000 and
  2026-10-02 −18000, today 2026-10-15: paid 18000, paid since 2026-09-09; fails on today's code.
Done when:
- C1 [cmd] `uv run pytest -q tests/energy/test_settlement.py -k "paid or grace"` passes: the gas pin above;
  electricity 2025-07-09..2025-12-31 then 2026-01-01..2026-12-31 with 2026-01-06 −20000 not paid and paid
  since 2026-01-15; a first period with no previous is paid since its start; credits never count
- C2 [cmd] `uv run pytest -q tests/energy/test_settlement.py -k settled` passes: previous settled −3169,
  a −3169 debit booked 2026-10-05 is not paid, a −3170 one is
- C3 [cmd] `uv run pytest -q tests/energy/test_settlement.py -k "advance_count or remaining"` passes:
  advance_count 11 for both 12-month periods, 5 for 2025-07-09..2025-12-31, 1 for a one-day period;
  gas with one advance paid on 2026-10-02 has 10 remaining; electricity paid Feb-Oct on the 6th has 2
- C4 [review] `meter_status` stays pure (no sqlite, no `date.today`, no float) and the service only passes
  the category's signed transactions
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N04 seasonal projection and suggested advance
Do: In `energy/settlement.py`, project the remaining days of the current period seasonally in meter units,
  take the worst case per day, and compute the suggested advance as the whole period's projected cost ÷
  `advance_count`. The per-day seasonal kWh for [as_of, settlement_date] is its own pure function, which
  the cycle chart (N07) reuses. The current daily rate no longer drives the projection or the worst case.
  The projected settlement stays paid + remaining advances − projected cost.
Context: D8: ratio month = latest calendar month fully inside the current period with every day in the
  daily usage before as_of; ratio = its units ÷ the same month a year earlier (fully covered, above 0, else
  no ratio); remaining day d in [as_of, settlement_date]: units = prev(d) × (1 + ratio) ÷ 2, prev(d) =
  usage on `same_day_last_year(d)` (`settlement.py:54`); kWh by the current period's factors
  (`_kwh_per_unit` `:172`), priced with its price and per-day fee (`_exact_cost_at_rate` `:208`); no ratio
  or no prev(d) → expected_kwh ÷ 365 kWh. D9 worst per day = max(seasonal, expected ÷ 365, prev(d) in kWh
  when known). D7 suggested = ceil to whole euros of (cost so far + projected rest) ÷ advance_count; None
  only without a projection. Fraction math, one rounding per shown figure. Replace `_last_year_rate`
  (`:217`) and `_suggested_advance` (`:241`). Moved pinned figures in other tests are updated, not loosened.
Read: `src/sonar/energy/settlement.py`, `tests/energy/test_settlement.py`
Write: `src/sonar/energy/settlement.py`, `tests/energy/test_settlement.py`, `tests/energy/test_service.py`,
  `tests/cashflow/test_service.py`, `tests/web/test_api_dashboard.py`, `tests/web/test_dashboard_page.py`,
  `tests/web/test_energy_page.py`, `tests/web/test_api_energy.py`
Test first: the owner's example on an electricity meter: last October 50 kWh, last November 100 kWh,
  this October 40 kWh, as_of 2026-11-01 → November projects exactly 90 kWh; fails on today's code.
Done when:
- C1 [cmd] `uv run pytest -q tests/energy/test_settlement.py -k seasonal` passes: the 40/50/100 → 90 pin;
  a day without last year's usage and a period without a ratio (no full month, or last year's month
  missing or 0) use expected_kwh ÷ 365; gas units convert with the current period's factors
- C2 [cmd] `uv run pytest -q tests/energy/test_settlement.py -k worst` passes: per day the highest of
  seasonal, expected ÷ 365 and last year's usage, each case winning once
- C3 [cmd] `uv run pytest -q tests/energy/test_settlement.py -k suggested` passes: 15200 ct for
  15701 kWh × 93800 µ€ + 12 × 1595 ct over 11; 26000 ct for 8558 kWh × 318325 µ€ + 12 × 1041 ct over 11;
  None without a projection
- C4 [review] no float, no `date.today`, no sqlite or web import in settlement.py; the daily rate is gone
  from projection and worst case; the per-day seasonal kWh is one reusable pure function
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N05 meter page
Do: Add the meter page `/energy/meters/{id}` and move the history there: the readings table with edit and
  delete, meter exchanges and billing periods with their lists and forms, and "Start new period". Slim the
  `/energy` meter card to the stats, the chart, the latest reading, the add-reading form, a "History,
  periods and exchanges" link and the delete-meter button. Move the form macros both pages use into
  `components/energy_forms.html`. Rebuild `sonar.css`.
Context: D13. Routes stay in `src/sonar/web/pages/energy.py` (`build_router` `:222`, `_submit` `:264`,
  `_delete` `:283`); edit and delete of a reading, exchange or period redirect (303) to and re-render their
  400 on their meter's page, found by a public store lookup over `_owner` (`src/sonar/energy/store.py:237`);
  add reading keeps `/energy`; an unknown meter id is 404 via `error.html`. Template today:
  `src/sonar/web/templates/energy.html:21-68` macros, `:136-254` chart and history sections. Hooks kept:
  `#meter-<id>-readings`, `-exchanges`, `-periods`, the form ids; new: `#meter-<id>-latest-reading` with
  `data-field` date and reading, `#meter-<id>-history` link, `#back-to-energy` on the meter page. Nav
  "Energy" keeps `aria-current` (`base.html:103`). Existing history tests move to the meter page.
Read: `src/sonar/web/pages/energy.py`, `src/sonar/web/templates/energy.html`, `src/sonar/energy/store.py:230-245`,
  `tests/html.py`, `tests/web/test_energy_page.py`
Write: `src/sonar/web/pages/energy.py`, `src/sonar/energy/store.py`, `src/sonar/web/templates/energy.html`,
  `src/sonar/web/templates/energy_meter.html`, `src/sonar/web/templates/components/energy_forms.html`,
  `src/sonar/web/static/sonar.css`, `tests/energy/test_store.py`, `tests/web/test_energy_page.py`,
  `tests/web/test_energy_meter_page.py`
Test first: GET `/energy/meters/<id>` for a meter with two readings shows `#meter-<id>-readings` newest
  first; fails with 404 because the route does not exist.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_energy_meter_page.py` passes: readings table, exchanges and
  periods with edit, delete and add forms and the start-new-period prefill; unknown id 404; nav Energy current
- C2 [cmd] `uv run pytest -q tests/web/test_energy_meter_page.py -k "redirect or invalid"` passes: an edit
  or delete answers 303 to `/energy/meters/<id>`; an invalid edit re-renders that page with 400,
  `#form-error` and the entered values
- C3 [cmd] `uv run pytest -q tests/web/test_energy_page.py -k "card or latest or history"` passes: the card
  has stats, chart, latest reading, add-reading form and the history link, and no readings table,
  exchange or period form
- C4 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o src/sonar/web/static/sonar.css --minify && git diff --exit-code src/sonar/web/static/sonar.css`
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N06 energy card figures and settled form
Do: Show the new figures on the `/energy` card: "Paid so far" with the hint "paid since <date>"; a "Last
  settlement" line under the stats when the previous period has a settled amount; the suggested advance's
  hint naming the advance count; the worst case hint matching D9. On the meter page add the period form's
  "Settled amount (€)" field (create, edit, start-new-period with it empty) and the settled amount in the
  period list. Rebuild `sonar.css`.
Context: D2 `paid_since` and D6 `advance_count` come on `MeterStatus`; D3 line "Last settlement:
  back-payment X on <date>" or "refund X on <date>" (amount by `eur`, date by `date`, previous period's
  settlement date); the field is optional and signed, prefill via `money`, 400 re-render keeps the value
  (SPEC §12). Page code `src/sonar/web/pages/energy.py` (PERIOD_FIELDS, `_period_from`, `_period_values`,
  next-period prefill); the period form macro is in `components/energy_forms.html`; the card stats in
  `energy.html`, the period list in `energy_meter.html`. Hooks: `#meter-<id>-paid-since`,
  `#meter-<id>-last-settlement` with `data-kind` refund|back-payment, `[data-field=settled]` in the period
  list, form input `settled`.
Read: `src/sonar/web/pages/energy.py`, `src/sonar/web/templates/energy.html`,
  `src/sonar/web/templates/energy_meter.html`, `src/sonar/web/templates/components/energy_forms.html`,
  `tests/html.py`
Write: `src/sonar/web/pages/energy.py`, `src/sonar/web/templates/energy.html`,
  `src/sonar/web/templates/energy_meter.html`, `src/sonar/web/templates/components/energy_forms.html`,
  `src/sonar/web/static/sonar.css`, `tests/web/test_energy_page.py`, `tests/web/test_energy_meter_page.py`
Test first: a meter whose previous period is settled −3169 shows `#meter-<id>-last-settlement` on `/energy`
  with data-kind back-payment and 31,69 €; fails because the hook does not exist.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_energy_page.py -k "paid_since or last_settlement or advance_count"`
  passes: paid since date shown; last settlement for back-payment and refund, absent without one; the
  suggested advance hint names the count
- C2 [cmd] `uv run pytest -q tests/web/test_energy_meter_page.py -k settled` passes: create and edit store a
  signed settled amount, empty stores none, an invalid one re-renders 400 with `#form-error` and the value
  kept, the start-new-period prefill is empty, the period list shows it
- C3 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o src/sonar/web/static/sonar.css --minify && git diff --exit-code src/sonar/web/static/sonar.css`
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N07 cycle chart
Do: Make each meter's chart show the previous and the current cycle with the current cycle's projected
  months. A pure function in `energy/settlement.py` returns the chart months (month, kWh, cost cents, cycle
  previous|current, projected yes|no); `MeterView` carries them in place of `month_figures`
  (`src/sonar/energy/service.py:37`); `energy_chart` (`src/sonar/web/templates/components/charts.html:180`)
  draws them. Rebuild `sonar.css`.
Context: D12 cycle months: a month belongs to the period in force on its 1st; current = the current
  period (none: latest, no projected months); previous = latest settlement before it; actual = months in
  `month_figures` (`settlement.py:93`); projected = the current cycle's months after its last actual one
  through the settlement month, measured days before as_of plus N04's per-day seasonal kWh from as_of to
  min(month end, settlement date), priced by the current period; at most 24, oldest previous dropped;
  trend over actual months only; fewer than 2 months keeps the empty text. D15 look: previous months
  muted, current actual solid, projected outlined or hatched, cost line dashed over projected months,
  legend entries for previous, current, projected, cost and projected cost; under 640px a current-only
  view (`sm:hidden`) replaces the full one (`hidden sm:block`). Hooks: rects `data-cycle`
  previous|current and `data-projected`, `data-series` cost and cost-projected, `data-view` all|current,
  `data-legend` per entry. Toggles and value labels keep working as today (`charts.html:197-202`).
Read: `src/sonar/energy/settlement.py`, `src/sonar/energy/service.py`,
  `src/sonar/web/templates/components/charts.html:174-252`, `src/sonar/web/charts.py:163-250`, `tests/html.py`
Write: `src/sonar/energy/settlement.py`, `src/sonar/energy/service.py`,
  `src/sonar/web/templates/components/charts.html`, `src/sonar/web/templates/energy.html`,
  `src/sonar/web/charts.py`, `src/sonar/web/static/sonar.css`, `tests/energy/test_settlement.py`,
  `tests/energy/test_service.py`, `tests/web/test_energy_page.py`, `tests/web/test_charts.py`
Test first: gas periods 2025-09-03..2026-08-25 and 2026-08-26..2027-08-25, usage 2025-07-01..2026-10-10,
  as_of 2026-10-10: Oct 2025-Aug 2026 previous, Sep 2026 current actual, Oct 2026-Aug 2027 projected;
  fails because the function does not exist.
Done when:
- C1 [cmd] `uv run pytest -q tests/energy/test_settlement.py -k cycle` passes: the gas pin above; Oct 2026
  sums measured days and seasonal days; Aug 2027 stops at the 25th; no current period shows the latest and
  the one before, nothing projected; a 30-month history keeps 24
- C2 [cmd] `uv run pytest -q tests/web/test_energy_page.py -k chart` passes: rects carry `data-cycle` and
  `data-projected`, cost and projected cost series, all legend entries, the current-only view
- C3 [review] no float or `date.today` in settlement.py; projected days reuse N04's seasonal function
- C4 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o src/sonar/web/static/sonar.css --minify && git diff --exit-code src/sonar/web/static/sonar.css`
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N08 remembered chart toggles
Do: Add one small inline script at the end of `energy.html`'s content that, for each `[data-energy-chart]`,
  restores its "Show values" and "Show trend" checkboxes from localStorage and saves them on change.
Context: D14: key per chart id and toggle (e.g. `energy-chart:meter-<id>-chart:values`), every
  localStorage call inside try/catch so a blocked storage leaves the default (off); no other behavior; the
  checkboxes work without the script through the `group-has` classes (`charts.html:197-202`). Inline
  scripts already exist in `src/sonar/web/templates/base.html:55-64` (the theme's localStorage pattern).
  No CSS change.
Read: `src/sonar/web/templates/energy.html`, `src/sonar/web/templates/base.html:55-64`,
  `src/sonar/web/templates/components/charts.html:196-205`, `tests/html.py`
Write: `src/sonar/web/templates/energy.html`, `tests/web/test_energy_page.py`
Test first: `/energy` with a meter has a script with `data-energy-chart-memory` that names localStorage
  and `data-toggle`; fails because it does not exist.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_energy_page.py -k toggle_memory` passes: one script on the page,
  it reads and writes localStorage inside try/catch; both checkboxes stay unchecked in the markup
- C2 [review] the script is small, keyed per chart id and toggle, touches only the checkboxes and fails
  silently without storage
- C3 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N09 visual check
Do: gate, pre-authorized (D10). Start the app per config `visual_recipe` on a temp DB (import the newest
  sample, set salary day and balance), then run the scratchpad loader of D10 (categories, synthetic Deutsche
  Bank CSV, rules, meters, readings, periods). Check /energy, both meter pages and / at desktop and 375px,
  light and dark (read_page first, scaled screenshots only where layout matters).
Done when:
- C1 [visual] /energy gas card: Paid so far 180,00 € paid since 09.09.2026 (the 2026-09-02 advance and the
  −31,69 back-payment not counted) and "Last settlement: back-payment 31,69 € on 25.08.2026"
- C2 [visual] /energy electricity card: Paid so far 1.800,00 € paid since 15.01.2026 (the −270,13 not
  counted) and "Last settlement: back-payment 270,13 € on 31.12.2025"
- C3 [visual] both cards show projected settlement, worst case and a suggested advance naming 11 advances,
  the latest reading, the add-reading form and the history link, and are short enough that the two charts
  sit close together
- C4 [visual] each chart: previous cycle muted, current actual solid, projected months outlined or hatched
  through the settlement month with a dashed cost line, a legend entry for each; at 375px only the current
  cycle shows
- C5 [visual] "Show values" and "Show trend" checked on one chart stay checked after a reload, the other
  chart unchanged
- C6 [visual] each meter page: readings table, exchanges and periods with forms; the period list shows the
  settled amount and the edit form prefills it; an invalid settled amount shows the inline error with the
  value kept; nav Energy is current
- C7 [visual] the dashboard Energy card lists both meters with the same settlement, worst case and suggested
  advance as /energy; nothing wraps, clips or scrolls sideways at 375px in light or dark

## N10 plan acceptance
Do: Check the whole plan against verify, SPEC §11 and §12 and the new Energy billing cycle bullet.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o src/sonar/web/static/sonar.css --minify && git diff --exit-code src/sonar/web/static/sonar.css`
- C3 [cmd] `! grep -rnE "float|date\.today|datetime\.now" src/sonar/energy`
- C4 [review] SPEC §11 checklist holds and SPEC §12 UI acceptance holds for /energy and the meter page
  (base.html, component macros, no inline `<style>`, 400 inline errors keeping values, `eur` amounts,
  `money` prefills, usable without script)
- C5 [review] the SPEC §13 Energy billing cycle bullet matches the code: grace window and paid since,
  settled amount and its exclusion, remaining advances, advance count, seasonal projection, worst case,
  suggested advance, meter page, cycle chart, remembered toggles; migration 0015 only adds a nullable column
- C6 [smoke] `uv run sonar` on a temp DB answers 200 on /, /energy and /api/energy, and on
  /energy/meters/<id> after `POST /api/energy/meters` creates one

## Log
