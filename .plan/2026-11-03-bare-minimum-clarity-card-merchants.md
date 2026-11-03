# Bare minimum clarity and card merchants
status: RUNNING
created: 2026-11-03 · updated: 2026-11-03
goal: card subscriptions are detected per merchant, and the Bare minimum card reads as answer, where it goes, next 6 cycles
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
commit: per-node
push: none
budgets: 2 tries per brief · 2 replans per node
tier: M

## Intent

Goal: Two independent improvements. A card subscription paid by debit card becomes its own recurring series named
after its merchant, so it shows on Fixed payments and in the forecast. The Bare minimum card answers "does income
cover a full pay cycle?" at a glance and then explains where the money goes and how the next six cycles look.

In scope: (A) detection-level grouping of card-settlement debits by the merchant at the start of the purpose, the
series name, a card-aware debt-draft match rule, and tests proving drifting card amounts still count and that
existing series and their edits survive. (B) a presentation-only redesign of the `bare-minimum-card` on the
dashboard in three zones (answer, where it goes, next 6 cycles), with new pure chart geometry and SVG macros. SPEC
§13 bullets for both parts.

Out of scope: any bare-minimum or breakdown number and the `/api/dashboard` shape; stored transactions, rules,
dedup and importers; key migration of old series; other dashboard cards.

Constraints: AGENTS.md rules: strict TDD, pure domain functions with `today` as a parameter, store-only DB access,
`components/` macros, `eur`/`date` filters, no inline `<style>`, page tests on ids and `data-*` through
`tests/html.py`, `sonar.css` rebuilt and committed, anonymized fixtures. Branches A (N02, N03) and B (N04, N05) run
in parallel with disjoint Write paths; SPEC.md is written once, after both. Confirmed Decisions D1-D14.

Definition of done: a fixture with several card merchants yields a monthly card series with drifting amounts, keyed
and named by its merchant; the card shows the three zones with the same numbers as `/api/dashboard`; full verify
passes; the visual gate passes on / and /recurring at desktop and 375px, light and dark; the final check confirms
SPEC §11 and §12.

## Decisions

- D1 A card-settlement debit is one whose `normalize_text(counterparty)` is in a module constant set holding "abrechnung karte"; it is checked before the mandate and creditor branches of `payment_key` (`src/sonar/recurring/detect.py:88-94`), because the Deutsche Bank export stamps every card row with its own mandate ref and the bank's creditor id, so today each card row is its own one-row group | confirmed
- D2 Merchant = purpose text before the first "//", whitespace-collapsed; key `card:<normalize_text(merchant)>`; a card row with no "//" or a blank merchant keeps today's key; same-day collisions still split into `#<rank>` via `series_keys` | confirmed
- D3 A card series' name is the merchant as written in its latest booking (whitespace-collapsed, at most `NAME_LENGTH`), e.g. "OPENAI .CHATGPT SUBSCR"; other series keep today's name rule (`detect.py:175`) | confirmed
- D4 Amount drift needs no code: detection ignores amounts and forecasts the latest one (`detect.py:155-178`); tests pin a monthly card series drifting 17,10-18,23 € as detected at the latest amount | confirmed
- D5 Survival: keys of non-card rows are unchanged, so existing series, their names, locks, descriptions and dismissals survive; old series keyed on card rows follow `sync_detected` as is (unedited deleted, edited kept; `src/sonar/recurring/store.py:213-248`); no migration | confirmed
- D6 A debt draft from a `card:` series matches on `purpose` with the merchant (`src/sonar/debts/drafts.py:73-80`), since counterparty "ABRECHNUNG KARTE" would match every card debit | confirmed
- D7 Zone 1: equation line Income − Bare minimum = Residual (residual coloured by sign), the tightest cycle label, a stacked SVG bar of fixed + lights-on against an income marker, and one sentence: "Tightest cycle <cycle>: income covers it with <residual> to spare|falls short by <−residual>. With <occasional> of occasional spending a month, that becomes a margin|shortfall of <margin>." | confirmed
- D8 Zone 2: two `<details>` rows, Fixed costs (cycle fixed cents, debt share as a small "<n>% debt" label) and Keep the lights on (expands to "<daily> a day × <n> days" and a /lights-on link). The fixed row holds `#fixed-breakdown`: groups as horizontal share bars in today's order, the first 5 visible and the rest in a "+N more" `<details>`, each group a `<details>` of its payments; and a note: monthly equivalent (`fixed_costs.monthly_equivalent_cents`) averages the year while the tightest cycle carries `cycle.fixed_cents` | confirmed
- D9 Zone 3: an SVG residual chart, one bar per cycle above or below a zero line, tightest marked; the cycle table behind "Show as table" `<details>`; "Upcoming debt endings" heading and table only when drops exist (`#bare-minimum-no-drops` goes) | confirmed
- D10 Hint state: zones absent; `#fixed-breakdown` still shows under the hint as a standalone section (SPEC.md:267 shows it in both states) | confirmed
- D11 Hooks kept with the same meaning: `#bare-minimum-card`, `-hint[data-reason]`, `#bare-minimum` (total, `[data-field=cycle]`), `-income`, `-residual`, `-fixed`, `-lights` (`[data-field=daily]`, `[data-days]`), `-debt-share[data-percent]`, `-occasional[data-margin]`, `-cycles` rows (`data-row`, `data-max`, fields), `-drops`, `#fixed-breakdown` (`data-total`, `data-count`, `[data-header]`, `[data-group]`, `[data-summary]`, `[data-percent]`, `[data-payment]`); new: `#bare-minimum-equation`, `-bar`, `-summary`, `-chart`, `-gap-note`, `#fixed-breakdown-more`; tests change only where D9 removes a hook | confirmed
- D12 Charts are inline SVG macros in `components/charts.html` whose geometry comes from new pure functions in `src/sonar/web/charts.py`; widths are SVG attributes (share bars may use a percent `width`), never a `style` attribute | confirmed
- D13 Parallel waves (N02 with N04, N03 with N05) as requested; Write paths are disjoint, and a `verify_fast` failure confined to the sibling branch's in-flight Write paths is re-checked after the sibling finishes, not replanned | confirmed
- D14 N07 visual gate pre-authorized: `uv run sonar import-categories data/categories.toml --db "$TMPDIR/sonar-visual.db"` first, then config `visual_recipe` on that temp DB | confirmed

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | preflight | check | - | -/- | 1 | 0 | DONE | |
| N02 | card merchant series keys | exec | N01 | gpt-6.1-sol@medium/sonnet | 1 | 0 | DONE | |
| N03 | card series sync, fixture and drafts | exec | N02 | gpt-6.1-sol@medium/sonnet | 1 | 0 | DONE | |
| N04 | bare minimum chart geometry | exec | N01 | gpt-6.1-sol@medium/sonnet | 1 | 0 | DONE | |
| N05 | bare minimum card zones | exec | N04 | gpt-6.1-sol@high/sonnet | 2 | 0 | DONE | |
| N06 | SPEC amendments | exec | N03,N05 | gpt-6.1-sol@medium/sonnet | 1 | 0 | DONE | |
| N07 | visual check | gate | N09 | -/sonnet | 0 | 1 | DONE | |
| N08 | plan acceptance | check | N07 | -/sonnet | 0 | 0 | TODO | |
| N09 | bare minimum card gate fixes | exec | N06 | gpt-6.1-sol@high/sonnet | 1 | 0 | DONE | |

## N01 preflight
Do: Confirm the starting point: verify passes on the untouched tree, the Tailwind CLI builds (the only download),
  `samples/` and `data/categories.toml` exist and the category import answers for the gate, the Codex CLI the
  executors run is on PATH, and the repo is writable. Tests need no network. A dirty tree (`.gitignore`,
  `.claude/launch.json`, this plan) is fine.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-preflight.css" --minify`
  exits 0 and writes outside the repo
- C3 [cmd] `test -n "$(ls samples/*.csv 2>/dev/null)" && test -f data/categories.toml`
- C4 [cmd] `uv run sonar import-categories --help` exits 0
- C5 [cmd] `command -v codex` exits 0
- C6 [cmd] `test -w .git/index && git status --porcelain >/dev/null`

## N02 card merchant series keys
Do: Group card-settlement debits by merchant in recurring detection. In `payment_key`
  (`src/sonar/recurring/detect.py:88-94`) return `card:<merchant>` for a card-settlement row before the mandate and
  creditor branches, and name a card series after its merchant in `_detect_group` (`detect.py:175`). Pure functions
  only; every non-card key stays byte-identical.
Context: D1 card-settlement = `normalize_text(counterparty)` (`src/sonar/importing/dedup.py:50`) in a module constant
  set holding "abrechnung karte". D2 merchant = purpose before the first "//", whitespace-collapsed; key uses
  `normalize_text(merchant)`; no "//" or blank merchant keeps today's key. D3 name = latest booking's merchant as
  written, whitespace-collapsed, at most `NAME_LENGTH`. D4 no amount filter; latest amount is forecast
  (`detect.py:165`). `payment_key` and `series_keys` also feed `debts/model.py:261-279` and `debts/drafts.py:44-55`,
  which stay consistent with no edit. Real card rows look like counterparty "ABRECHNUNG KARTE", purpose
  "OPENAI .CHATGPT SUBSCR//SAN FRANCISCO/US 01-09-2026T07:24:30 Kartennr. 5354…", a per-row unique mandate ref and a
  shared bank creditor id; fixtures use invented merchants and ids. D13: N04 runs beside this node; a failure only in
  its Write paths (`src/sonar/web/charts.py`, `components/charts.html`, `tests/web/test_charts_bare_minimum.py`) is
  not this node's.
Read: `src/sonar/recurring/detect.py`, `tests/recurring/test_detect.py:1-60`, `tests/recurring/test_detect.py:380-460`
Write: `src/sonar/recurring/detect.py`, `tests/recurring/test_detect_card.py`
Test first: two card rows of different merchants with distinct mandate refs and one creditor id get keys
  `card:<merchant>`; four monthly rows of one merchant among weekly rows of another detect as one series named after
  the merchant.
Done when:
- C1 [cmd] `uv run pytest -q tests/recurring/test_detect_card.py tests/recurring/test_detect.py`
- C2 [review] tests cover: card key ignores mandate ref and creditor id; case and spacing variants of the label and
  merchant share a key; no "//" and blank merchant keep today's key; a non-card row's key is unchanged; two same-day
  charges of one merchant split into `#1`/`#2`; weekly merchant rows are not detected; the series name is the
  merchant as written
- C3 [review] a monthly card series with amounts drifting between 1710 and 1823 cents is detected with
  `amount_cents` equal to the latest amount (D4); no amount check was added
- C4 [review] the merchant logic is pure, has domain names and one constant for the label set; `test_detect.py` is
  unchanged
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N03 card series sync, fixture and drafts
Do: Prove card series end to end and fix debt drafts for them. Add an anonymized Deutsche Bank CSV fixture with
  several card merchants, import it in a store test and run `sync_detected` (`src/sonar/recurring/store.py:213`).
  In `_match_rule` (`src/sonar/debts/drafts.py:73-80`) return a `purpose` rule with the merchant for a `card:`
  detection key.
Context: D5 non-card keys unchanged; a renamed (name-locked) or described card series keeps its edits on re-sync; an
  existing non-card series with a locked name keeps it when card rows are added; no migration. D6 the draft rule for
  a card series is `MatchRule("purpose", <merchant>)` (`src/sonar/debts/model.py:36-47`), so it matches only that
  merchant's debits. Fixture format: `tests/fixtures/db_girokonto.csv` and
  `src/sonar/importing/importers/deutsche_bank_giro.py:40-60`; card rows carry counterparty "ABRECHNUNG KARTE",
  purpose "<MERCHANT>//<CITY>/<CC> <date>T<time> Kartennr. <masked>", a per-row unique mandate ref and one shared
  creditor id. Include a monthly "STREAMCO .VIDEO SUBSCR" drifting 17,10-18,23 €, a weekly grocer, and one-offs;
  invented names, IBANs and ids only. Store-test pattern: `tests/recurring/test_store_sync.py:1-66`. Runs after N02
  is committed. D13: N05 runs beside this node; a failure only in its Write paths is not this node's.
Read: `tests/fixtures/db_girokonto.csv`, `tests/importing/test_store.py:1-40`, `tests/recurring/test_store_sync.py`,
  `src/sonar/debts/drafts.py`, `tests/debts/` (the drafts tests), `src/sonar/recurring/detect.py`
Write: `tests/fixtures/db_girokonto_cards.csv`, `tests/recurring/test_store_sync_card.py`, `src/sonar/debts/drafts.py`,
  `tests/debts/test_drafts_card.py`
Test first: importing the fixture and syncing stores exactly one active detected series named "STREAMCO .VIDEO
  SUBSCR", monthly, at the latest amount; a draft prefill for a `card:` series in a debt category matches on purpose.
Done when:
- C1 [cmd] `uv run pytest -q tests/recurring/test_store_sync_card.py tests/debts/test_drafts_card.py`
- C2 [review] the store test checks name, key prefix `card:`, interval 1, the latest amount, no series for the
  grocer or the one-offs, a locked rename of the card series surviving a second sync, and a locked non-card series
  surviving the card import
- C3 [review] the fixture holds no real merchant, name, IBAN, card number or creditor id; `samples/` is not read by
  any test
- C4 [review] `_match_rule` changes only for `card:` keys; existing drafts tests pass unchanged
- C5 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N04 bare minimum chart geometry
Do: Add the pure geometry and SVG macros the new card needs. In `src/sonar/web/charts.py` add a need-bar function
  (fixed and lights-on segment widths plus an income marker x, on a scale of max(need, income)) and a residual-bars
  function (for signed values: y, height and sign per bar around a zero line, the largest magnitude filling the
  height). In `components/charts.html` add `need_bar(...)` and `residual_chart(...)` macros using them, plus a
  `share_bar(percent)` macro, each with `<title>` and `aria-label`.
Context: D12 geometry in Python, SVG attributes only, no `style` attribute; a share bar may use `width="<n>%"`. D7
  need bar: fixed + lights-on segments and an income marker; `data-part="fixed|lights|income"` and `data-cents` on
  each element. D9 residual chart: one bar per cycle, `data-cents`, `data-max` on the tightest, a zero line. Model on
  `stacked_columns`/`bars` (`src/sonar/web/charts.py:174-191`, `_scale` at `:292`) and `category_bars`
  (`src/sonar/web/templates/components/charts.html:118-138`); Jinja calls Python helpers through `charts.`. Amounts
  in titles use `eur`. Integer cents in, integer pixels out. D13: N02 runs beside this node; a failure only in its
  Write paths (`src/sonar/recurring/detect.py`, `tests/recurring/test_detect_card.py`) is not this node's.
Read: `src/sonar/web/charts.py`, `src/sonar/web/templates/components/charts.html:1-140`, `tests/web/test_charts.py:1-80`,
  `src/sonar/cashflow/bare_minimum.py:15-45`
Write: `src/sonar/web/charts.py`, `src/sonar/web/templates/components/charts.html`, `tests/web/test_charts_bare_minimum.py`
Test first: need-bar segments add up to the need's width with income beyond it putting the marker past the bar;
  residual bars of [+300, −100] put the first above and the second below the zero line.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_charts_bare_minimum.py tests/web/test_charts.py`
- C2 [review] function tests cover: income above, equal to and below the need; zero lights-on; all-zero values;
  all-positive, all-negative and mixed residuals; rounding keeps segments summing to the bar
- C3 [review] macro tests render each macro and assert on `data-part`, `data-cents`, `data-max`, `<title>` and
  `aria-label`, never on CSS classes; no `style=` in the new macros
- C4 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N05 bare minimum card zones
Do: Rebuild the numbers state of `#bare-minimum-card` (`src/sonar/web/templates/index.html:218-313`) as three zones
  using the N04 macros: 1 answer, 2 where it goes, 3 next 6 cycles. Presentation only: every number comes from
  `dashboard.bare_minimum`, `dashboard.fixed_breakdown` and `dashboard.fixed_costs` as today. Rebuild and commit
  `sonar.css`.
Context: D7 zone 1 equation, cycle label, need bar, sentence. D8 zone 2 rows, share bars, top 5 plus "+N more",
  debt label on the fixed row, gap note. D9 zone 3 residual chart, cycle table behind "Show as table" (like
  `index.html:190-191`), drops only when non-empty. D10 hint state keeps `#fixed-breakdown` standalone. D11 keep the
  listed hooks with the same meaning, add the new ones; update tests only where D9 removes `#bare-minimum-no-drops`.
  Displayed amounts use `amount`/`eur`, dates `date`, cycle labels `charts.cycle_label`; no inline `<style>`; no
  change to Python outside templates. Page-test helpers: `tests/html.py`. D13: N03 runs beside this node; a failure
  only in its Write paths is not this node's.
Read: `src/sonar/web/templates/index.html:1-30`, `src/sonar/web/templates/index.html:170-345`,
  `src/sonar/web/templates/components/charts.html`, `tests/html.py`, `tests/web/test_dashboard_bare_minimum.py`,
  `tests/web/test_dashboard_fixed_breakdown.py`
Write: `src/sonar/web/templates/index.html`, `src/sonar/web/static/sonar.css`, `tests/web/test_dashboard_bare_minimum.py`,
  `tests/web/test_dashboard_fixed_breakdown.py`
Test first: the card shows `#bare-minimum-equation` whose income, total and residual cents equal `load_dashboard`'s
  `bare_minimum`, and `#bare-minimum-summary` carrying the residual and occasional margin.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_dashboard_bare_minimum.py tests/web/test_dashboard_fixed_breakdown.py tests/web/test_dashboard_page.py tests/web/test_templates_hygiene.py`
- C2 [review] page tests check zone order (equation, bar, summary, then fixed and lights rows, then chart, table)
  and that every shown number equals the dashboard object: equation, need bar parts, sentence, debt label, gap note
  (monthly equivalent and cycle fixed), share bars, residual bars per cycle with the tightest marked
- C3 [review] tests cover 7 groups (5 visible, `#fixed-breakdown-more` says "+2 more"), 3 groups (no "+N more"),
  positive and negative residual and margin wording, drops present and absent (no heading, no table), hint state with
  the standalone breakdown
- C4 [review] all D11 hooks exist with the same meaning; no other existing test was edited
- C5 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-n05.css" --minify && cmp "$TMPDIR/plz-n05.css" src/sonar/web/static/sonar.css`
- C6 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N06 SPEC amendments
Do: Add two SPEC §13 bullets at the end of `SPEC.md`. "Card merchant series (§6 Detection)": D1-D6, stating it
  overrides the grouping bullet at `SPEC.md:87` for card-settlement debits. "Bare minimum card layout (§9, §12)":
  D7-D11, stating it overrides the layout sentence (D8) of the Bare minimum bullet at `SPEC.md:266` and the
  presentation sentences of the Fixed costs breakdown bullet at `SPEC.md:267`, with all numbers and the API unchanged.
Context: D1 label set "abrechnung karte" checked before mandate and creditor. D2 merchant before "//", key
  `card:<normalized merchant>`, fallback to today's key. D3 name = merchant. D4 drift allowed, latest amount. D5 no
  migration, edits survive. D6 card drafts match on purpose. D7-D10 the three zones and hint state. D11 hooks. Read
  the code from N02-N05 and describe what it does; where code and a Decision differ, report it rather than editing
  code.
Read: `SPEC.md:82-92`, `SPEC.md:225-269`, `src/sonar/recurring/detect.py`, `src/sonar/debts/drafts.py`,
  `src/sonar/web/templates/index.html`
Write: `SPEC.md`
Test first: -
Done when:
- C1 [review] both bullets exist in §13, name the sections they override, and match `detect.py`, `drafts.py` and
  `index.html`
- C2 [cmd] `uv run pytest -q -x && uv run ruff check .`

## N07 visual check
Do: gate, pre-authorized (D14). Run `uv run sonar import-categories data/categories.toml --db "$TMPDIR/sonar-visual.db"`,
  then start the app per config `visual_recipe` on `$TMPDIR/sonar-visual.db`. Import the newest file in `samples/` on
  /import, then on /settings set salary day 26 and a balance as of the sample's last booking date. Check / (the Bare
  minimum card: expanding the Fixed costs row, a group, "+N more", the Keep the lights on row, "Show as table") and
  /recurring at desktop and 375px, light and dark (read_page first, scaled screenshots only where layout matters),
  then stop the app.
Done when:
- C1 [visual] zone 1 shows the equation, the need bar with income marker and one sentence "Tightest cycle <cycle>:
  income covers it with X to spare | falls short by X. With X of occasional spending a month, the margin shrinks to
  X | that becomes a shortfall of X | the gap grows to X." with no negative amount and no double negative; the
  numbers equal `GET /api/dashboard` `bare_minimum` (as magnitudes in the sentence)
- C2 [visual] zone 2 shows Fixed costs and Keep the lights on as two collapsed rows, each summary showing its name
  and total, the fixed summary also a small "<n>% debt" label; opening Fixed costs shows the gap note and share bars,
  at most 5 visible, "+N more" when there are more, each group expanding to its payments; opening Keep the lights on
  shows the daily amount × days and a /lights-on link; totals equal `fixed_breakdown`
- C3 [visual] zone 3 shows the residual chart spanning the card width, every bar labelled with its cycle and amount,
  the tightest cycle marked, the table behind "Show as table", and debt endings only when `bare_minimum.drops` is
  non-empty
- C4 [visual] /recurring lists at least one detected card series named after its merchant (not "ABRECHNUNG KARTE"),
  monthly, at its latest booked amount
- C5 [visual] at 375px nothing on either page is cut off or overflows and the chart labels do not overlap; light and
  dark are both readable

## N08 plan acceptance
Do: Whole-plan check: run the full verify, then confirm SPEC §11 (acceptance checklist) and §12 (UI) still hold for
  the dashboard and Fixed payments, and that the two new §13 bullets match the code.
Done when:
- C1 [cmd] `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`
- C2 [review] SPEC §11 items (`SPEC.md:162-177`) hold: detection intervals and next due dates, dismissed and edited
  payments surviving re-detection, the Fixed costs section; non-card detection keys are unchanged
- C3 [review] SPEC §12 UI rules hold: `base.html`, `components/` macros, no inline `<style>`, `eur`/`date`, page tests
  on ids and `data-*`, `sonar.css` rebuilt and committed; `/api/dashboard` and `cashflow/` are unchanged by this plan
- C4 [review] the §13 bullets match `detect.py`, `drafts.py`, `charts.py` and `index.html`, including D1-D12; no
  migration was added and no importer, rule or dedup file changed

## N09 bare minimum card gate fixes
Do: Four presentation fixes to the numbers state of `#bare-minimum-card`; no number, Python domain code or API
  changes. (1) Zone 1 sentence in the D7 form. (2) Residual chart spans the card width and labels every bar with its
  cycle and amount. (3) Fixed costs and Keep the lights on become collapsed `<details>` rows. (4) Debt share becomes
  the small "<n>% debt" label in the Fixed costs summary. Update the §13 layout bullet, rebuild and commit `sonar.css`.
Context: (1) `index.html:286-292`: "Tightest cycle <cycle_label>: income covers it with <r> to spare." or "income
  falls short by <|r|>." then "With <occasional> of occasional spending a month, the margin shrinks to <m>." (r, m
  >= 0), "that becomes a shortfall of <|m|>." (r >= 0 > m) or "the gap grows to <|m|>." (r < 0). Amounts are
  magnitudes, `colored=false`; signed cents stay on the `<p>`'s `data-residual`/`data-margin`.
  (2) `residual_chart` (`components/charts.html:322-342`): a fixed viewBox width of 300 like `category_bars`
  (`charts.html:119-123`), slot = width / cycles, `block w-full` with no fixed height so it is not letterboxed; each
  bar gets an amount text (`data-part="amount"`, `|eur`) on its outer end and a cycle text (`data-part="cycle"`,
  `charts.day_month(c.start)`) below the chart; full `cycle_label` stays in each `<title>`; legible at 375px, no overlap.
  (3) `index.html:296-316`: `#bare-minimum-fixed` and `#bare-minimum-lights` are `<details>` (not `open`), summary
  `details_summary` (`index.html:18`) with the name and total (first `data-cents` in the row is the total); fixed
  summary also holds `#bare-minimum-debt-share`; inside fixed: `#bare-minimum-gap-note` and `{{ fixed_breakdown }}`;
  inside lights: "<daily> a day × <n> days" and a /lights-on link. (4) `#bare-minimum-debt-share[data-percent]` reads
  "<n>% debt", small and muted, no sentence and no debt amount. Hint state, all other D11 hooks, zone order and
  `#fixed-breakdown` markup are unchanged. No inline `<style>`, no `style=`. SPEC: rewrite only the presentation
  sentences of `SPEC.md:272` that these four points change.
Read: `src/sonar/web/templates/index.html:1-30`, `src/sonar/web/templates/index.html:218-345`,
  `src/sonar/web/templates/components/charts.html:118-140`, `src/sonar/web/templates/components/charts.html:300-351`,
  `tests/html.py`, `tests/web/test_dashboard_bare_minimum.py`, `tests/web/test_charts_bare_minimum.py:60-100`,
  `SPEC.md:272`
Write: `src/sonar/web/templates/index.html`, `src/sonar/web/templates/components/charts.html`,
  `src/sonar/web/static/sonar.css`, `tests/web/test_dashboard_bare_minimum.py`, `tests/web/test_charts_bare_minimum.py`,
  `SPEC.md`
Test first: the summary text matches each of the three wordings above for positive, mixed and negative fixtures, and
  `#bare-minimum-fixed` is a closed `details` whose `summary` holds the total and `#bare-minimum-debt-share`.
Done when:
- C1 [cmd] `uv run pytest -q tests/web/test_dashboard_bare_minimum.py tests/web/test_charts_bare_minimum.py tests/web/test_dashboard_fixed_breakdown.py tests/web/test_templates_hygiene.py`
- C2 [review] page tests pin the three sentence wordings with magnitudes in `data-field` residual, occasional and
  margin, and no "-" amount or "below zero" in the sentence
- C3 [review] macro tests assert one `data-part="amount"` and one `data-part="cycle"` text per bar, viewBox width
  300, no fixed height class on the svg; bars, `data-max` and the zero line keep their meaning
- C4 [review] both rows are `<details>` without `open`, summaries as in Context (3); debt share shows "<n>% debt" only;
  hint state, other D11 hooks and zone order unchanged; `SPEC.md:272` describes the four changes
- C5 [cmd] `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o "$TMPDIR/plz-n09.css" --minify && cmp "$TMPDIR/plz-n09.css" src/sonar/web/static/sonar.css`
- C6 [cmd] `uv run pytest -q -x && uv run ruff check .`

## Log

### N01 try 1 · 2026-11-03
check: PASS 6/6

### N04 try 1 · 2026-11-03
exec: DONE · 2199 passed; ruff check clean; 91 chart tests passed; formatting clean
- Added integer need and signed residual geometry plus accessible need, residual and debt share SVG macros.
- Residual zero is at height with equal space on either side; data-max marks minimum residual cycles. CSS rebuild matches tracked bundle.

### N02 try 1 · 2026-11-03
exec: DONE · 72 recurring tests passed; 2184 passed excluding parallel N04 tests; ruff check and changed-file format check passed
- Added pure card merchant keys and latest merchant names; fallback keys unchanged; 20 new tests observed 8 fail before implementation.
- Full Verify stopped at tests/web/test_charts_bare_minimum.py missing need_bar; D13 exemption applied using PYTEST_ADDOPTS=--ignore=tests/web/test_charts_bare_minimum.py.

### N04 try 1 · 2026-11-03
check: PASS 2/2

### N02 try 1 · 2026-11-03
check: PASS 2/2

### N04 try 1 · 2026-11-03
verify: PASS

### N02 try 1 · 2026-11-03
verify: PASS

### N03 try 1 · 2026-11-03
exec: DONE · 2208 passed; ruff check clean; changed Python files formatted
- Added synthetic card CSV and five tests covering monthly detection, latest amount, excluded grocer and one-offs, preserved card edits and locked non-card names.
- Card draft rules use the merchant purpose; non-card matching unchanged. Focused draft and card tests: 21 passed.
check: PASS 2/2

### N05 try 1 · 2026-11-03
exec: DONE · 2208 passed; ruff check and format clean; CSS reproducibility passed
- Rebuilt the card as equation, composition and six-cycle zones; retained hooks and hint breakdown; rebuilt sonar.css.
- Added failing-first dashboard comparisons, positive and negative wording, visible share bars, 3/7 group disclosure and debt-ending coverage; kept cycle table behind Show as table.

### N03 try 1 · 2026-11-03
verify: PASS

### N05 try 1 · 2026-11-03
check: PASS 3/3
verify: FAIL C4
- C4 src/sonar/web/templates/index.html - D11 new hooks #bare-minimum-bar, #bare-minimum-chart, #bare-minimum-gap-note do not exist (page uses #bare-minimum-need-bar, #bare-minimum-residual-chart, #bare-minimum-fixed-gap; tests assert those names) - expected the D11 hook names

### N05 try 2 · 2026-11-03
exec: DONE · 2208 passed; ruff check and format clean; CSS rebuild matches
- Corrected D11 hooks in index.html and corresponding page assertions: bare-minimum-bar, bare-minimum-chart, bare-minimum-gap-note.
- Preserved previous implementation; confirmed failing hook assertions before the template fix.
check: PASS 3/3
verify: PASS

### N06 try 1 · 2026-11-03
exec: DONE · 2208 passed; ruff check clean
- Added SPEC §13 Card merchant series D1-D6 and Bare minimum card layout D7-D11 amendments.
- Documented implemented detection, draft matching, three-zone layout and stable hooks; retained calculation and API rules.
check: PASS 1/1
verify: PASS

### N07 try 1 · 2026-11-03
human: gate defects: (1) zone 1 sentence reads 'you have -504,35 EUR (a shortfall) ... leaving a margin of -851,18 EUR below zero' (double negative); use the D7 form: 'Tightest cycle <cycle>: income falls short by 504,35 EUR | covers it with X to spare. With 346,83 EUR of occasional spending a month, the gap grows to 851,18 EUR | the margin shrinks to X.' (2) zone 3 residual chart has no cycle labels and no amounts and does not span the card width; label each bar with its short cycle and amount, full width like the Fixed costs chart. (3) Fixed costs and Keep the lights on are not collapsible rows as D8 says; make each a details row (summary: name, total, and for fixed the small debt label), the breakdown and the lights detail inside, collapsed by default. (4) debt share is a full sentence; show it as the small '<n>% debt' label in the Fixed costs summary. Card series on /recurring, 375px layout and both themes pass.

### N07 replan 1 · 2026-11-03
plan: REPLANNED +N09
- Cause: the gate found 4 card defects: double-negative sentence, unlabelled letterboxed residual chart, fixed and lights rows not collapsible, debt share as a sentence.
- Added N09 (exec, deps N06, gpt-6.1-sol@high/sonnet) to fix all four in index.html, charts.html, tests, sonar.css and SPEC.md:272; N07 now depends on N09.
- N07 brief rewritten: criteria pin the D7 sentence wording, collapsed rows with the percent-debt label, full-width labelled chart and no label overlap at 375px.

### N09 try 1 · 2026-11-03
exec: DONE · 2210 passed; ruff check clean; focused 34 passed; CSS rebuild comparison clean
- Updated summary magnitudes and three wordings, collapsed composition rows, debt label, chart labels and width, SPEC presentation, and generated CSS.
- Kept signed summary attributes, existing hooks, fixed breakdown markup, calculations, and API unchanged.
check: PASS 3/3
verify: PASS
