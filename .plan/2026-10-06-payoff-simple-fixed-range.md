# Payoff simple fixed range
status: DONE
created: 2026-10-06 · updated: 2026-10-06
goal: The Payoff page's fixed-cost min and max come from the current fixed-payment rows (monthly rows for min, every row at full amount for max) instead of a 12-month calendar window.
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: S

## Intent

Goal: the Payoff page shows "fixed costs now" and each step's "after" as a min–max range computed by summing the cheapest and dearest calendar months over the 12 full months after the estimate date. That range is hard to read and hangs on calendar quirks. The new rule is simpler and works straight from the current fixed-payment rows (the same rows the dashboard Fixed costs card lists, debts included). Min is what is paid every month. Max is every payment at its full amount. Each step takes away the included debts' rates, counting only the monthly ones for min.

In scope: the pure ladder in `src/sonar/debts/payoff.py`; `load_payoff` in `src/sonar/cashflow/service.py`, with its 12-month window and per-debt month series removed; a small pure range helper next to the fixed-cost rows in `src/sonar/cashflow/forecast.py` (D2); their tests; the SPEC §13 Payoff ladder bullet.

Out of scope: templates and CSS, the step slider and `static/payoff.js`, the dashboard and its Fixed costs card and chart (`forecast.month_totals` stays, the chart still uses it), the ordering of steps, pay-now totals and freed per month.

Constraints: AGENTS.md rules: strict TDD, integer cents, the estimate date passed in as a parameter, pure core with a thin service, `tests/test_architecture.py` import rules, no dead code left behind, ruff clean. Decisions D1-D5 below.

Definition of done: a pure test runs the worked example (monthly rows 3000 incl. TV 40, car 700, mortgage 1500, plus a quarterly laptop 450: now 3000–3450; step TV freed 40, after 2960–3410; step laptop freed 490, after 2960–2960). Service tests show a quarterly row counted only in max. The payoff page tests pass unchanged. SPEC states the new rule. The plan `verify` passes.

## Decisions

- D1 "Current fixed-payment rows" = `forecast.fixed_costs(sources, estimate_date).rows` over `_fixed_sources(conn, views, txs)` (`src/sonar/cashflow/service.py:156`, `:286`), i.e. the dashboard card's rows, debts included, each at its `amount_cents` and `interval_months` | confirmed
- D2 The row range lives in a pure `fixed_range(rows) -> tuple[int, int]` in `src/sonar/cashflow/forecast.py` (min = sum of rows with interval_months <= 1, max = sum of all rows), and `payoff_ladder(debts, now_min_cents, now_max_cents)`, so `debts` stays free of `cashflow` imports | confirmed
- D3 Step after: min = now min − sum of `rate_cents` of included debts with interval_months <= 1 (loans already have interval 1, `service.py:109`); max = now max − sum of `rate_cents` of all included debts; freed unchanged (sum of included rates). Rates are subtracted even where a debt's row amount differs from its rate; no clamping at 0 | confirmed
- D4 Removed as dead: `LadderDebt.months`, the months-length check and its test, `window_start` and the 12-month docstring in `load_payoff`, the month series in `_ladder_debt`, and the test helper `_fixed_totals` (`tests/cashflow/test_service.py:662`) if nothing else uses it. `Payoff.before_min_cents`/`before_max_cents` stay and hold the now range | confirmed
- D5 No template change, so no visual gate and no CSS rebuild; `tests/web/test_payoff_page.py` must pass unchanged | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | payoff range from fixed rows | exec | - | sonnet/sonnet | 1 | 0 | DONE | |

## N01 payoff range from fixed rows
Do: Replace the Payoff ladder's 12-month calendar min/max with the rule over current fixed-payment rows: now min = monthly rows (interval_months <= 1), now max = every row at full amount; each step subtracts the included debts' rates (monthly ones only for min). Rewire `load_payoff` to use those rows, delete the month-window code, and rewrite the SPEC §13 bullet.
Context: D1: rows = `forecast.fixed_costs(sources, estimate_date).rows` (`src/sonar/cashflow/forecast.py:106`, `FixedCostRow` `:39`) over `_fixed_sources` (`src/sonar/cashflow/service.py:286`), the same as the dashboard (`service.py:156`).
  D2: add pure `fixed_range(rows) -> tuple[int, int]` in `forecast.py` next to `fixed_costs`; `payoff_ladder(debts, now_min_cents, now_max_cents)` in `src/sonar/debts/payoff.py:41`; `debts` imports nothing from `cashflow`.
  D3: after_min = now_min − sum(rate_cents of included debts with interval_months <= 1); after_max = now_max − sum(rate_cents of all included); freed = sum of included rates; before_* = now range; no clamp. Ordering and pay-now unchanged (`payoff.py:49-52`).
  D4: delete `LadderDebt.months` (`payoff.py:24`), the length check (`:44-48`) and its test, `window_start` and the 12-month docstring (`service.py:82-98`), the month series in `_ladder_debt` (`:103`, `:118`), and `_fixed_totals` (`tests/cashflow/test_service.py:662`) if unused. Rewrite the `payoff.py` module docstring to say why min and max differ (non-monthly payments). `forecast.month_totals` stays (`forecast.py:108`).
  D5: no template or CSS change; `tests/web/test_payoff_page.py` unchanged.
  SPEC: rewrite the bullet at `SPEC.md:255` in place: replace the "min and max over the 12 full months ..." clause with the D1/D3 rule and say "Fixed costs now" shows the same min–max; keep the slider and `payoff.js` sentences.
Read: `src/sonar/debts/payoff.py`, `tests/debts/test_payoff.py`, `src/sonar/cashflow/service.py:72-120`, `src/sonar/cashflow/forecast.py:39-60`, `src/sonar/cashflow/forecast.py:106-118`, `tests/cashflow/test_service.py:655-795`, `tests/cashflow/test_forecast.py:40-90`, `SPEC.md:255`
Write: `src/sonar/debts/payoff.py`, `tests/debts/test_payoff.py`, `src/sonar/cashflow/forecast.py`, `tests/cashflow/test_forecast.py`, `src/sonar/cashflow/service.py`, `tests/cashflow/test_service.py`, `SPEC.md`
Test first: in `tests/debts/test_payoff.py`, the worked example with shuffled input: now 300000–345000; debts TV (installment, rate 4000, monthly, remaining 30000), laptop (installment, rate 45000, interval 3, remaining 100000), car (loan, 70000), mortgage (loan, 150000), remaining ascending in that order; step 1 TV freed 4000 after 296000–341000; step 2 laptop freed 49000 after 296000–296000; steps 3 and 4 freed 119000 and 269000 after 226000–226000 and 76000–76000.
Done when:
- C1 [cmd] `uv run pytest -q tests/debts/test_payoff.py tests/cashflow/test_forecast.py`
- C2 [review] `test_payoff.py` holds the worked example above; the zero-remaining, tie-order and no-debts tests remain, adapted to the new signature; the months-length test is gone. `test_forecast.py` has a `fixed_range` test with a monthly and a quarterly row (min = monthly only, max = both) and an empty-rows case giving (0, 0).
- C3 [review] `LadderDebt` has no `months` field; `payoff_ladder` takes (debts, now_min_cents, now_max_cents) and `src/sonar/debts/payoff.py` imports nothing from `sonar.cashflow`; integer cents only, type hints, docstring explains why.
- C4 [cmd] `uv run pytest -q tests/cashflow/test_service.py tests/web/test_payoff_page.py`
- C5 [review] `load_payoff` takes the rows from `forecast.fixed_costs(..., estimate_date)` and `fixed_range`; the service payoff tests no longer assert `.months` or the 12-month window: one shows a quarterly fixed row counted in max only (before and after), the mid-month test is replaced by one proving the range comes from the rows at the estimate date, and the linked-recurring test still gives after 0–0 and freed 10000.
- C6 [cmd] `! grep -nE "window_start|12 full months|_fixed_totals" src/sonar/debts/payoff.py src/sonar/cashflow/service.py tests/cashflow/test_service.py SPEC.md`
- C7 [review] Only the bullet at `SPEC.md:255` changes in SPEC, stating min = monthly fixed rows, max = all rows at full amount, after = minus included rates (monthly only for min), freed unchanged, "Fixed costs now" the same range; no template, CSS or `payoff.js` file is in the diff.
- C8 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`

## Log

### N01 try 1 · 2026-10-06
exec: DONE · 1273 passed
- payoff_ladder(debts, now_min, now_max) with forecast.fixed_range over fixed_costs rows; LadderDebt.months, window_start, month check, _fixed_totals removed
- load_payoff uses rows at the estimate date; SPEC §13 payoff bullet rewritten
check: PASS 4/4
verify: PASS
