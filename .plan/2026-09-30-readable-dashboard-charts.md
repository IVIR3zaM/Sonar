# Readable dashboard charts
status: RUNNING
created: 2026-09-30 · updated: 2026-09-30
goal: the runway bar and the Fixed costs column chart show their values at a glance, without hovering
request: runway legend with values and a visible limit/0/balance scale under the bar; a compact value label above each Fixed costs column; SPEC §12 accessibility kept; page tests on data-* hooks; gate at desktop and 375px, light and dark
spec: SPEC §12 (Design system, Display formats, Pages: Dashboard, UI acceptance), §11
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
budgets: 2 tries per brief · 2 replans per node

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | runway scale geometry | exec | - | sonnet/opus | 1 | 0 | DONE | |
| N02 | runway scale and legend values | exec | N01 | sonnet/sonnet | 1 | 0 | DONE | |
| N03 | column value labels | exec | N02 | sonnet/sonnet | 1 | 0 | DONE | |
| N06 | readable column labels | exec | N03 | sonnet/sonnet | 1 | 0 | DONE | |
| N04 | visual check | gate | N06 | - | 0 | 1 | WAITING | |
| N05 | plan acceptance | check | N01,N02,N03,N06,N04 | -/sonnet | 0 | 0 | TODO | |

## Open questions

- none (Q1 resolved: European style "1,2k €", "12k €", "950 €", applied in N03)
- Q2 At 375px a column slot is ~26px, so twelve horizontal "1,2k €" labels at a readable ~11px overlap their neighbours; rotate each label vertically above its column (keeps the Q1 format), or drop " €" and keep them horizontal? | recommend: rotate vertically, keeping "1,2k €" (N06 is written for this)

## Nodes

### N01 runway scale geometry
Do: Add a pure function `runway_scale(limit, balance, worst, best) -> list[ScaleMark]` to `sonar.charts`. It places the overdraft limit, zero and balance marks as percentages along the runway axis, so HTML labels can sit under the SVG. The SVG uses `preserveAspectRatio="none"` (`charts.html:8`), so SVG text would stretch. `ScaleMark` is a frozen dataclass with `part` ("limit" | "zero" | "balance"), `cents`, `percent` (float, 0–100, one decimal), `align` ("start" | "center" | "end") and `row` (int, 0-based). Derive the positions from the existing axis by calling `runway(..., width=1000)` (`charts.py:25`) and dividing by 10, so labels line up with the SVG marks. Don't duplicate the low/high/span logic.
Rules:
- Order the marks by percent. Marks with equal cents collapse into one and keep balance over limit over zero. For example, limit 0 gives only the zero and balance marks, and limit 0 with balance 0 gives only the balance mark.
- Alignment: "start" when percent < 12.5, "end" when percent > 87.5, else "center". This keeps edge labels inside the bar's width.
- Overlap: set a module constant `SCALE_MIN_GAP = 25` (percent; a label like "−1.500,00 €" at text-xs is about a quarter of the bar at 375px). Assign rows greedily in percent order: each mark takes the lowest row whose previous mark is at least `SCALE_MIN_GAP` percent away. Otherwise it opens a new row. At most 3 rows exist because there are at most 3 marks.
- A comment explains *why* labels are HTML rather than SVG text.
Spec: SPEC §12 Pages: Dashboard (runway bar spanning overdraft limit, 0 and balance); src/sonar/charts.py:16-41
Read: src/sonar/charts.py, tests/test_charts.py:1-60
Write: src/sonar/charts.py, tests/test_charts.py
Test first: `runway_scale(-50000, 100000, -20000, 30000)` returns limit, zero, balance at 0.0, 33.3, 100.0 with aligns start, center, end, all on row 0. It fails because the function doesn't exist.
Done when:
- C1 `runway_scale(-50000, 100000, -20000, 30000)` gives parts `["limit", "zero", "balance"]`, percents `[0.0, 33.3, 100.0]`, aligns `["start", "center", "end"]`, rows `[0, 0, 0]` (tested).
- C2 Two marks less than `SCALE_MIN_GAP` apart land on different rows. For example, `runway_scale(-5000, 3000, -400000, -300000)` puts limit, zero and balance within a few percent of each other at the right end, on rows 0, 1 and 2, with no two marks on the same row closer than `SCALE_MIN_GAP` (tested).
- C3 The dedup cases are tested: limit 0 yields no "limit" mark, and limit 0 with balance 0 yields exactly one mark, part "balance".
- C4 For every mark, `percent * 3` is within 1.5 of the matching x from `runway(..., 300)` (limit_x, zero_x, balance_x) (tested on at least two inputs, including the "detached track" input at `tests/test_charts.py:58`).
- C5 The all-zero input `runway_scale(0, 0, 0, 0)` returns one balance mark at 0.0 without error (tested).
- C6 `charts.py` has no `date.today()` and no float money; cents stay int.
- C7 The verify command exits 0.
Findings:
- none

### N02 runway scale and legend values
Do: Make the runway readable without hovering.
(a) In the `runway_bar` macro (`src/sonar/templates/components/charts.html:4`), after the `</svg>`, render a scale from `charts.runway_scale(limit, balance, worst, best)`. It is a `<div data-scale aria-hidden="true">` with `relative`, `mt-1`, `text-xs`, muted text and a height class picked by row count from a literal Jinja list (`h-4`, `h-8`, `h-12`). Each mark is an absolutely positioned `<span>` with `data-part`, `data-cents` and `data-row`, `style="left: {{ percent }}%"` (the precedent is `debts.html:27`), a top class from a literal list (`top-0`, `top-4`, `top-8`), a translate class from its align (start: none, center: `-translate-x-1/2`, end: `-translate-x-full`), and `whitespace-nowrap`. Label text: limit and balance use `|eur`, zero shows `0`.
(b) In `src/sonar/templates/index.html:79-83`, the legend items show their values: "Overdraft zone down to <limit>", "Projected at payday <worst> to <best>", "Balance today <balance>". Each `<li>` gets `data-legend="overdraft"`, `"projected"` or `"balance"`, and each amount uses the `amount` macro with `colored=false`, carrying `data-cents`. Add no `id`: `#overdraft-limit` already exists at `index.html:58`. Keep the swatches and the legend's `aria-hidden="true"`: the SVG `aria-label` (`charts.html:7`) already carries every value for screen readers.
Rebuild `sonar.css` with the command in CLAUDE.md Setup.
Spec: SPEC §12 Pages: Dashboard, Design system, Display formats; CLAUDE.md UI conventions
Read: src/sonar/templates/components/charts.html:1-40, src/sonar/templates/index.html:40-84, src/sonar/charts.py (runway_scale from N01), tests/test_charts.py:13-23 and :98-135, tests/test_dashboard_page.py:95-120 and :330-370, tests/html.py
Write: src/sonar/templates/components/charts.html, src/sonar/templates/index.html, src/sonar/static/sonar.css, tests/test_charts.py, tests/test_dashboard_page.py
Test first: a macro test (`render` fixture, `tests/test_charts.py:13`) where `runway_bar(-50000, 100000, -20000, 30000)` renders `[data-scale]` with three spans whose `data-part` are limit, zero, balance, `data-cents` are -50000, 0, 100000, and whose texts contain "−500,00 €", "0" and "1.000,00 €". It fails because no scale exists yet.
Done when:
- C1 The macro test in "Test first" passes, and each scale span's `style` holds its `left:` percent from `runway_scale`.
- C2 A macro test with close marks (e.g. `runway_bar(-5000, 3000, -400000, -300000)`) shows distinct `data-row` values for the close spans.
- C3 A dashboard page test reads `#runway [data-legend=overdraft]`, `[data-legend=projected]` and `[data-legend=balance]` through `tests/html.py`: the overdraft item holds the limit's cents, the projected item holds worst then best, and the balance item holds the balance. Its text starts "Overdraft zone down to", "Projected at payday" and "Balance today".
- C4 The existing runway tests (`tests/test_charts.py:98-135`, `_runway` in `tests/test_dashboard_page.py:101`) still pass. The SVG keeps `role="img"`, `aria-label` and `<title>`s. The page has no duplicate `id`s.
- C5 No inline `<style>` element was added. Amounts use `eur`/`amount`, not `money`.
- C6 Rebuilding the CSS leaves `sonar.css` unchanged afterwards (`git diff --exit-code src/sonar/static/sonar.css` after a rebuild).
- C7 The verify command exits 0.
Findings:
- none

### N03 column value labels
Do: Show each month's Fixed costs total above its column.
(1) Add a pure `compact_eur(cents) -> str` to `src/sonar/charts.py`, reached in templates through the `charts` global (`app.py:230`). It uses the magnitude only, because columns show size, not sign (`charts.py:82`). It uses integer arithmetic only: euros = (|cents| + 50) // 100. Below 1000 € it gives "<euros> €". From 1000 € up to 9.999 € it gives one decimal of thousands, rounded half up with a comma and a trailing ",0" dropped ("1,2k €", "1k €"). From 10.000 € up it gives whole thousands rounded half up ("12k €"). The space before € is non-breaking, as in `display.py:14`. This is the European style matching `eur` (SPEC §12 Display formats): suffix "€", decimal comma, never the "€1.2k" prefix/dot style.
(2) In `month_columns` (`charts.html:42`), add above each column a `<text data-part="value" data-cents="{{ m.total_cents }}">` with `text-anchor="middle"`, `font-size="7"` and muted fill, centered on the slot, 2 units above the column top. Extend the viewBox upward (e.g. `0 -10 W height+22`) so the peak's label isn't clipped. Keep the peak column's amber highlight (`charts.html:54`), the rect `data-cents`, the `<title>` with the full `eur` value, and the month labels. The existing macro test selects `svg.find_all("rect")`, so don't add rects. Rebuild `sonar.css`.
Spec: SPEC §12 Pages: Dashboard (12-month SVG column chart), Display formats
Read: src/sonar/charts.py, src/sonar/display.py:12-42, src/sonar/templates/components/charts.html:42-62, tests/test_charts.py:13-23 and :62-80 and :137-150
Write: src/sonar/charts.py, src/sonar/templates/components/charts.html, src/sonar/static/sonar.css, tests/test_charts.py
Test first: `compact_eur(-123456) == "1,2k €"`, and the unit test fails because the function doesn't exist. Then a macro test: `month_columns` over the months at `tests/test_charts.py:138-142` renders three `[data-part=value]` texts reading "0 €", "100 €" and "50 €" with matching `data-cents`.
Done when:
- C1 `compact_eur` is tested on at least: 0 → "0 €", -95049 → "950 €", 99950 → "1k €", -123456 → "1,2k €", 100000 → "1k €", 996000 → "10k €", -1234567 → "12k €" (each with a non-breaking space).
- C2 The macro test in "Test first" passes. Each value text's y is above its column's top (`y < rect y`), and the rect list and heights of `tests/test_charts.py:137-150` are unchanged.
- C3 The peak column keeps its amber fill class and every rect keeps its `<title>` with the full `eur` value.
- C4 The svg still has `role="img"`, `aria-label` and a `<title>`, and no label is clipped: every value text's y is ≥ the viewBox's min-y.
- C5 Rebuilding the CSS leaves `sonar.css` unchanged afterwards (`git diff --exit-code src/sonar/static/sonar.css` after a rebuild).
- C6 The verify command exits 0.
Findings:
- none

### N06 readable column labels
Do: Make the Fixed costs value and month labels readable at desktop and 375px (gate N04 try 1: value labels rendered at ~7–9px). The chart scales with `preserveAspectRatio` meet, so 1 viewBox unit ≈ 1.05px at 375px (≈ 300px wide / 288 units) and is height-bound at desktop by `h-28` (`charts.html:60`). Change only the `month_columns` macro (`charts.html:54-76`):
(1) Value labels (`charts.html:70-71`): `font-size="10"`, `text-anchor="start"`, `dominant-baseline="central"`, anchored at the slot centre and 3 units above the column top, with `transform="rotate(-90 <x> <y>)"` so the text reads upward inside its own slot and never reaches a neighbour. Keep `data-part="value"`, `data-cents`, the muted fill classes and `compact_eur` unchanged.
(2) Month labels (`charts.html:72-73`): `font-size="10"`, still horizontal, below the columns.
(3) Headroom: set the viewBox min-y to -40 (the longest label, "123k €", is about 34 units at font 10) and grow its height to cover the month labels; move nothing else. Change the svg's size class from `h-28` to `h-36 sm:h-48` so the text renders at ≥ 10px at 375px and larger at desktop.
Keep the rects, their heights, `data-cents`, `<title>`s and the peak's amber class exactly as they are. Rebuild `sonar.css` with the command in CLAUDE.md Setup.
Spec: SPEC §12 Pages: Dashboard (12-month SVG column chart), Design system, UI acceptance
Read: src/sonar/templates/components/charts.html:54-76, tests/test_charts.py:13-30, :238-269 and :309-315
Write: src/sonar/templates/components/charts.html, src/sonar/static/sonar.css, tests/test_charts.py
Test first: extend or add a macro test over the months at `tests/test_charts.py:255-259`: every `[data-part=value]` has `font-size` "10" and a `transform` starting with "rotate(-90"; the viewBox min-y is ≤ -38. It fails because the labels are horizontal at font-size 7 and min-y is -10.
Done when:
- C1 The "Test first" test passes, and each value text's rotate pivot equals its own `x` and `y` attributes.
- C2 Each value text's `x` lies within its column's rect (`rect x ≤ x ≤ rect x + width`), and its `y` is below the viewBox min-y by at least 36 and above its rect top (`y < rect y`).
- C3 Every month label (the text without `data-part`) has `font-size` "10" and a `y` within the viewBox (min-y ≤ y ≤ min-y + height).
- C4 `tests/test_charts.py:238-269` still pass unchanged apart from the new assertions: rect list, heights, `data-cents`, `<title>`s and value texts ("0 €", "100 €", "50 €").
- C5 The svg keeps `role="img"`, `aria-label` and `<title>`; no inline `<style>`; no new rect.
- C6 Rebuilding the CSS leaves `sonar.css` unchanged afterwards (`git diff --exit-code src/sonar/static/sonar.css` after a rebuild).
- C7 The verify command exits 0.
Findings:
- none

### N04 visual check
Do: Gate. Following the CLAUDE.md Visual check, the orchestrator starts the app on a temp DB, imports the real sample, and sets the salary day, balance and a non-zero overdraft limit. It checks the dashboard `/` in the browser pane at desktop and 375px, light and dark (read_page first, scaled screenshots of the hero card and the Fixed costs card only). Also check a case where the limit, 0 and balance marks sit close together, e.g. a balance just above 0 with a small limit.
Done when:
- C1 The runway legend shows the limit, the worst-to-best range and the balance as text, readable in both themes.
- C2 The scale labels sit under their marks with no overlapping text and none outside the card, at desktop and 375px, including the close-marks case.
- C3 Each Fixed costs column shows a readable compact value above it (vertical, rendered text ≥ ~10px, per N06), with no overlap or clipping at 375px, the month labels are readable, and the peak column is still highlighted.
- C4 No horizontal scroll at 375px.
Findings:
- try 1: C1 C2 C4 pass (desktop and 375px, light and dark, incl. limit −100 € / balance 50 € close-marks case: scale labels stagger into 3 rows, no overlap). C3 fails: the Fixed costs column value labels render at font-size 7 in the viewBox and measure ~9px tall at desktop and ~7px at 375px, too small to read; the SVG is height-bound (h-28) so at desktop the chart fills only ~300 of 638px card width and the labels do not grow. Peak highlight and no clipping are fine.

### N05 plan acceptance
Do: check the whole plan against its goal.
Done when:
- C1 the verify command exits 0
- C2 SPEC §11 still holds for the areas this plan touched (dashboard)
- C3 SPEC §12 UI acceptance holds: the CSS rebuild leaves `sonar.css` unchanged, `uv run sonar` starts, no inline `<style>`, displayed amounts use `eur`/`amount`, and the charts keep `role="img"`, `aria-label` and `<title>`
- C4 The runway values (limit, worst, best, balance) and every month's Fixed costs total are in visible text on `/`, asserted by page or macro tests on `data-*` hooks
Findings:
- none
