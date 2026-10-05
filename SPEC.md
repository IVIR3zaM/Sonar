# Sonar: Product Spec

What the app does. It is the source of truth for behavior. How we work (the graph workflow, engineering rules, conventions, token discipline) lives in `AGENTS.md`. Section numbers are stable, because code, migrations and plans cite them (`SPEC §6`).

## 0. What we're building

A local web app for our household. It imports bank exports, categorizes transactions, detects fixed costs, tracks installments and loans, and forecasts whether we'll get through to the next salary day.

- Binds 127.0.0.1; optional Google sign-in (§13 Sign-in).
- Data comes in by file upload for now. A live bank connection (Enable Banking or FinTS) may come later. Don't build it, but don't design anything that blocks it.

## 1. How we work

Moved to `AGENTS.md` (Graph workflow). Plans live in `.plan/`.

## 2. Engineering rules

Moved to `AGENTS.md` (Engineering rules). The Verifier enforces them.

## 3. Stack (already decided)

- Python 3.12 with uv.
- FastAPI with server-rendered Jinja2 pages and HTMX for small interactions. No SPA, no JS build step.
- SQLite via stdlib `sqlite3` with plain SQL. No ORM.
- pytest and ruff.
- M6 amendment (user, 2026-09-24): styling uses Tailwind CSS v4 via the `pytailwindcss` standalone CLI (dev only, no Node). The built `src/sonar/web/static/sonar.css` is committed, so `uv run sonar` still needs no build step. htmx is vendored under `src/sonar/web/static/`, not loaded from a CDN.

Why this stack: Python has the best tooling for CSV and PDF parsing (pdfplumber later) and for German banking (python-fints, Enable Banking examples), and this is the fewest moving parts for a local app.

Additional setup:

- Schema changes go in numbered SQL migration files, applied at startup and tracked in a table. Hand-entered data (payment schedules, debts, settings) must survive upgrades.
- `data/` (the database) and `samples/` (real exports) are gitignored. Real bank data is never committed.
- The app starts with one command.

## 4. Import

- I can upload one or more files at once. For each file, show: the format detected, rows added, rows skipped as duplicates, and rows left uncategorized.
- **Format detection.** Each source format is one importer module implementing `detect(file) -> bool` and `parse(file) -> list[ParsedTransaction]`, registered in a single list. The app picks the importer whose `detect` matches. If none matches, show a clear error listing the supported formats. Adding a source must mean one new module plus its fixture tests, and no other changes.
- **Build now: the Deutsche Bank current account (Girokonto) CSV.**
  - Do not rely on memory for its layout. Derive the parser from the real export in `samples/`, and create an anonymized fixture from it for the tests.
  - Record the confirmed layout (columns, encoding, separators, preamble and footer) in a short comment at the top of the importer module.
  - Expect a German locale: `;` separator, decimal comma, `dd.mm.yyyy` dates, preamble lines before the header, a balance line after the rows, and possibly Windows-1252 encoding. Confirm each of these against the sample.
- **Later, not now:** Consorsbank credit card statements as PDF, and other banks. The design must keep this easy to add. Once a second source exists, the credit card settlement debit on the Girokonto and transfers between our own accounts must not be counted as spending twice. The `transfer` category type (section 5) exists for this.
- **Stored per transaction:** source/account, booking date, value date, amount, currency, counterparty, purpose text, and a copy of the raw row. When present, also store IBAN, mandate reference and creditor ID, which are strong signals for recurrence.
- **Current balance.** If an export contains an account balance, store it with its date. I can also set the balance manually in Settings. The entry with the latest date wins.

### Idempotency

Re-importing the same file or an overlapping file adds only the rows not already stored.

- The fingerprint is a hash of the normalized account, booking date, amount, counterparty and purpose text.
- Genuinely identical rows, such as two equal purchases on the same day, must both be kept. Within a file, number the duplicates of each fingerprint (occurrence 1, 2, ...) and make `(fingerprint, occurrence)` unique. Re-importing then adds 0 rows.
- Required tests:
  - the same file imported twice;
  - two files with overlapping date ranges;
  - two identical rows in one file;
  - the same file with its rows in a different order.

## 5. Categorization (defined by Claude Code, not by hand in the app)

- Categories and rules live in one readable file in the codebase: `categories.toml`.
  - Each category has a type: `income`, `fixed`, `variable` or `transfer`.
  - Rules are ordered and the first match wins. A rule matches on counterparty or purpose text (case-insensitive substring or regex), optionally combined with amount sign, an absolute amount range, IBAN or creditor ID.
- **Initial taxonomy.** In M2, propose a small household set of categories based on my real sample. I will not maintain it by hand.
- Rules are re-applied to all stored transactions on every import and at startup, so rule changes take effect everywhere.
- **Loop for unknown transactions.**
  1. The "Uncategorized" page has a copy button that produces one self-contained text block to paste into Claude Code. It contains:
     - A first line reading exactly: `Categorization request: follow the Categorization workflow in CLAUDE.md.`
     - The uncategorized transactions grouped by normalized counterparty, one line per group: count, amount range, date range, and up to 2 sample purpose texts truncated to about 80 characters.
     - Nothing else. Keep it compact.
  2. I paste it into Claude Code, which updates the rules (see the next bullet).
  3. I re-upload the same file or press "Re-apply rules". No duplicates appear, and the previously unknown rows are now categorized.
- **`CLAUDE.md` must document the Categorization workflow:**
  - Add or extend categories and rules in `categories.toml`, creating new categories when needed.
  - Add one test case per new rule to the table-driven rules test.
  - Run the tests. Touch nothing else.
  - Reply in at most 5 lines listing the new rules.
  - Handle it directly in the main session, without the agent graph.
- The dashboard shows the uncategorized count.

## 6. Fixed and recurring payments

### Detection

- Detection runs over outgoing transactions, excluding the `variable` and `transfer` categories.
- Group transactions by mandate reference or creditor ID when present; otherwise by normalized counterparty.
- Classify the interval as every 1, 2, 3, 6 or 12 months. Tolerate about ±7 days for weekends and bank processing. Store the interval as a number of months, not a named enum. "Bi-monthly" in this project means every two months.
- Require enough evidence: at least 3 occurrences for 1-, 2- and 3-month intervals, and at least 2 for 6- and 12-month intervals.
- The amount may vary moderately (utilities). Forecasts use the latest amount.
- Each recurring payment has: name, category, amount, interval, typical day of month, last paid date and next due date.

### Corrections (the "Fixed payments" page)

- I can edit the name, amount, interval and day.
- I can dismiss a false positive. It stays dismissed on re-import and re-detection.
- I can add a recurring payment manually.
- **Schedules change over time.** Real example: water supply is €240 every 2 months until November, then it stops. Around February the new amount is set and payments resume.
  - I must be able to say "ends or pauses after <date>" and "resumes on <date> with amount X every N months".
  - Model this as a list of schedule periods per payment, each with: from, optional until, amount, interval and day. Forecasts use whichever period is valid on each date.
- My edits always win. Detection never overwrites them.
- Required test, the water example end to end: payments are forecast through November, none in December or January, and the new amount from February.

## 7. Installments and loans

- The UI has two sections backed by one model: `debt`, with kind `installment` or `loan`.
- **Installment:** name, total amount, rate, interval, first payment date and number of payments. Shows paid so far, amount remaining, payments remaining and end date.
- **Loan:** name, remaining balance as of a date (taken from the loan statement), monthly rate and optional interest rate. Shows the projected balance today and the payoff date. Use simple amortization when an interest rate is given; otherwise linear.
- Each debt has a match rule (counterparty or mandate reference) that links it to the real bank payments. "Paid so far" is counted from those transactions.
- Debt payments count as fixed costs in the forecast. If a detected recurring payment is the same thing, link the two so nothing is counted twice.
- A fully paid debt drops out of the forecast.

## 8. Settings

- **Salary day of month**, for example 26. When it falls on a weekend, payday is the Friday before. Public holidays are out of scope until I ask.
- **Current balance override** (see section 4).

## 9. Dashboard

One page that answers "are we going to be OK?" at a glance.

**Top: traffic light.** The projected balance on the day before the next payday, shown as a range [worst, best].

- Green: worst ≥ 0.
- Yellow: best ≥ 0 but worst < 0.
- Red: best < 0.

**Below it, four sections:**

1. **Until next payday (<date>, in N days):**
   - the current balance;
   - fixed payments still due before payday, as a total ("€500 expected") and a list of name, date and amount;
   - variable spending forecast as a range ("€400–600 more"), with a per-category breakdown such as groceries;
   - the projected balance range.
2. **Fixed costs:**
   - the monthly-equivalent total (annual payments divided by 12, and so on);
   - a list sorted by day of month showing when each payment occurs and at what interval;
   - per-month totals for the next 12 months, so heavy months (such as annual insurance) stand out.
3. **Installments and loans:** the amount remaining per item, plus the total.
4. **Uncategorized:** the count, with a link to the page.

**Variable range method.** Keep it simple and explainable, and show the method in a tooltip.

- A salary cycle runs from one payday to the day before the next.
- Take total `variable` spending in each of the last 6 complete cycles and scale each value to the days remaining in the current cycle.
- The range is the 25th to 75th percentile of those scaled values.
- The per-category breakdown uses the median per category.
- With fewer than 3 complete cycles of history, show "not enough data".

## 10. Milestones

M0–M6 are done. Their task graphs, replans and commits are in `.plan/2026-09-23-initial-build-m0-m6.md`. New work gets a new plan (`AGENTS.md`).

- **M0 Skeleton:** uv project, ruff, pytest, FastAPI hello page, migration runner, `CLAUDE.md`, `.claude/agents/`, `.gitignore`.
- **M1 Import:** importer registry, Deutsche Bank CSV importer built from the sample in `samples/`, idempotent storage, upload page with results. Importing the real sample must succeed.
- **M2 Categorization:** `categories.toml` with the initial taxonomy, rule engine, re-apply, Uncategorized export, the Categorization workflow in `CLAUDE.md`.
- **M3 Recurring payments:** detection, schedule periods, and the UI to edit, pause, resume, dismiss and add payments.
- **M4 Installments and loans.**
- **M5 Forecast, dashboard and settings.**
- **M6 UI redesign:** see section 12.

## 11. Acceptance checklist (the Verifier uses this at the end)

- [ ] Starts locally on 127.0.0.1 with one command, with no login.
- [ ] Deutsche Bank CSV upload, including several files at once.
- [ ] Same file twice adds 0 rows; overlapping files add only the missing rows; identical same-day rows are both kept.
- [ ] An unknown format gives a clear error. A new format needs only one module plus its tests.
- [ ] Unknown-transaction loop works: Uncategorized export, paste into Claude Code, rules and tests added, re-upload categorizes the rows with no duplicates.
- [ ] Monthly, 2-monthly, quarterly, half-yearly and annual payments are detected with the correct next due date.
- [ ] Water example: pause after November, resume in February with the new amount, forecast correct.
- [ ] Dismissed and edited payments survive re-import and re-detection.
- [ ] The salary day is configurable and weekend paydays are handled.
- [ ] The dashboard shows fixed payments due before payday (total and list), the variable range, the payday projection and the traffic light.
- [ ] The Fixed costs section shows the monthly equivalent, when each payment occurs, and the next 12 months per month.
- [ ] Installments and loans each show their remaining amount.
- [ ] All tests are green, ruff is clean, and the code meets section 2.

## 12. UI (M6)

Presentation only. Domain modules (`cashflow/forecast.py`, `cashflow/service.py`, `debts/model.py`, `recurring/store.py`, `variable_forecast.py`) and their tests stay unchanged, unless a template needs a value no domain object exposes yet.

**Tooling**

- Tailwind source is `src/sonar/web/static/src/app.css`: `@import "tailwindcss"`, `@source` pointing at the templates, `@theme` tokens (colors, radius, fonts) and a dark variant. The build command is in `AGENTS.md` Setup.
- Mount `StaticFiles` at `/static` in `create_app`. Vendor htmx under `static/vendor/`.
- No JS framework. Use native `<details>`/`<dialog>`, `hx-confirm` and small inline progressive-enhancement scripts only.

**Design system**

- Jinja macros in `templates/components/`: card, stat, badge, button, field (label, input, error), amount, empty state, charts. Pages compose them; no page-level inline `<style>`.
- Shell in `base.html`: sidebar on desktop, top bar with a drawer on mobile. Active item from `request.url.path`. An Uncategorized count badge loaded from a small htmx fragment route, and updated out of band by `/reapply`.
- Light and dark themes follow `prefers-color-scheme`, with a toggle remembered in `localStorage`. No horizontal scroll at 375px width.

**Display formats**

- New `eur` filter/macro: `1.234,56 €` (non-breaking space, `−` minus), colored by sign, wrapped with `data-cents="<int>"`.
- `money` stays unchanged for form `value=` prefills, because `parse_signed_cents` must round-trip them.
- Dates display as `24 Sep 2026` inside `<time datetime="YYYY-MM-DD">`.

**Pages**

- **Dashboard:** hero card with a status pill (green "On track", yellow "Tight", red "Overdraft risk"), the worst→best range at payday, days to payday, and balance with its as-of date. An SVG runway bar spanning overdraft limit, 0 and balance, with the projected band marked. A Due card (list plus total) and a Variable spending card (range, bars per category median, the existing method tooltip kept). A Fixed costs card: monthly-equivalent stat, 12-month SVG column chart, rows table. A Debts card with the total. An uncategorized callout when the count is above 0. Charts are server-rendered inline SVG macros with `<title>` and accessible labels; no chart library.
- **Fixed payments:** compact table (name with debt badge, category badge, amount, cadence like "every 3 mo · day 15", last paid, next due). One Edit drawer per row with Edit, Pause and Resume sections and the period timeline. Dismiss asks for confirmation. Add payment is a card form.
- **Installments and loans:** one card per debt with kind badge, paid-off badge, progress bar, facts grid, match line and linked payments. Delete asks for confirmation. The Add forms are collapsible cards. Total remaining as a stat.
- **Import:** dropzone around the file input, htmx loading indicator, results with added/duplicate/uncategorized badges; an error row renders as an alert.
- **Uncategorized:** count badge, "Re-apply rules" with a spinner, rows table, the Claude request in a monospace panel, Copy with "Copied" feedback.
- **Settings:** Household and Balance cards with labelled fields and help text; current balance as a stat.

**Friendly errors**

- Every POST that returns a plain-text 400 today re-renders its page with status 400, an inline `#form-error` alert, and the entered values kept. GET and error paths share one render helper per page.
- A 404 renders a styled `error.html`.

**Tests:** page tests assert on stable hooks (ids, `data-*` attributes) through `tests/html.py`; see `AGENTS.md` UI conventions.

**UI acceptance (the Verifier checks this on any UI change)**

- [ ] pytest green, ruff clean; the section 11 checklist still holds.
- [ ] Rebuilding the CSS leaves `src/sonar/web/static/sonar.css` unchanged (`git diff --exit-code`).
- [ ] `uv run sonar` starts without the Tailwind binary or network access.
- [ ] Every page extends `base.html`, uses the component macros, and has no inline `<style>`.
- [ ] Invalid form input shows an inline error with status 400 and keeps the entered values.
- [ ] Displayed amounts use `eur`; form prefills use `money`.

## 13. Amendments (user decisions, override earlier sections)

- Detection (§6): a detected series that has stopped (judged against the latest booking date) is dropped. Edited and dismissed payments are kept.
- Loans (§7): a loan pays monthly on its as-of day, starting the month after. An installment's last payment is `total − (n−1) × rate` when that is above 0, else `rate`.
- Forecast (§9): the window is [balance date + 1, payday − 1]. Balance dates in the future are rejected.
- Traffic light (§9): an overdraft limit (default −500,00 €, editable in Settings) replaces 0. Green: worst ≥ limit. Yellow: best ≥ limit. Red: otherwise.
- Categorization (§5): `categories.toml` may use real counterparty names and IBANs. Tests use fake strings only.
- Categorization config (§5, §10 M2, §11): categories and ordered rules live in the SQLite DB and are edited on a Categories page linked from Settings and Uncategorized (add, edit, delete categories; add, edit, delete, reorder rules; invalid regex, unknown category and a rule with no text condition are friendly 400 errors); every change re-applies rules and re-runs detection. `categories.toml` is no longer shipped or read by the app; the repo seeds generic categories and no rules; `uv run sonar import-categories PATH` replaces the DB taxonomy from a local TOML file. The §11 unknown-transaction loop now means: export, rules added on the Categories page or by Claude Code through the API (bullet below), rows categorized on re-apply.
- Personal data: real names and IBANs live only in the local DB and gitignored local files; this replaces the earlier Categorization bullet above; tracked files, tests and commit messages never contain them.
- Groups (§5, §6, §9, §12): each category has one group (`type`): `income`, `transfer`, `fixed` (Fixed payments: housing/rent, mortgage, loans and installments, utilities, phone and internet, insurance, subscriptions), `lights_on` (Keep the lights on: spending we can reduce but not bring to zero, e.g. groceries, transport, shopping) or `occasional` (Occasional payments: fees and taxes, education, donations, health, dining and similar one-offs); `variable` is replaced by the last two, and §6 detection excludes `lights_on`, `occasional` and `transfer`.
- Monthly page: totals per group (Fixed payments, Keep the lights on, Occasional payments, and Uncategorized when not zero) and the transfers stat as the net per month, the signed sum of all `transfer`-category bookings in the month, labelled "Net moved to other accounts" (or "Net received from other accounts" when positive).
- Accounts: only the imported main account counts for the forecast; sub-accounts are not imported and have no balances or reserves.
- Forecast (§9): the variable range is replaced by two parts: 1 · Fixed payments due before payday (unchanged) and 2 · Keep the lights on: expected = the day-weighted daily average debit spend in `lights_on` categories over the last 3 complete months (salary months as on the Monthly page) × the window's days; range = lowest and highest of those months' daily averages × days; no complete month gives "not enough data"; the dashboard states the expected shortfall or margin against 0; Occasional and uncategorized debits are not forecast.
- Pages (§11, §12): a "Keep the lights on" page plots the daily average per month for the group total, each of its categories and the Occasional total; §11's "variable range" now means the Keep-the-lights-on part; §12's Variable spending card is now the Keep the lights on card; `variable_forecast.py` is removed from §12's list of unchanged domain modules.
- Categorization API (§3, §5): the running app serves JSON endpoints under `/api/` to list categories (with group) and ordered rules, create, update and delete categories and rules, move a rule to a position, and read the uncategorized transactions grouped like the export; the Categories page and the API share one service layer (same validation and messages), errors are 4xx JSON, and every write re-applies rules and re-runs detection; local only, no auth. §5's "defined by Claude Code" now means Claude Code proposes changes from the API's current state and writes them through the API only after the owner confirms; it edits no repo file and adds no tests for rules.
- Keep the lights on months (§9, §12): a month counts as complete only when it ends on or before both the last imported booking and the balance date. The dashboard and the Keep the lights on page learn from the same months, and the page shows the per-day figures (expected, lowest and highest month, months used) that the dashboard multiplies by the days from the balance date to payday.
- Expected at payday (§9, overrides the "against 0" clause of the Forecast bullet above): expected = balance + recurring income − due − expected Keep the lights on (recurring income as in the Recurring income bullet below). At or above 0 the dashboard says "About X to spare"; below 0 but at or above the overdraft limit, "About X into your overdraft, Y before the limit" (Y = expected − limit); below the limit, "About Y past your overdraft limit".
- Estimate date (§9, overrides "today" in the dashboard): every dashboard estimate is based on the balance's as-of date, the estimate date: the next payday is the first payday after it, the window is [estimate date + 1, payday − 1], and fixed costs and debt remainders are computed as of it; days to payday still count from today and are negative when the data predates that payday. The dashboard shows "Estimated from <date>", labels the runway marker "Balance on <date>", and when the payday has passed it says the data ends before it and links to Import.
- Instructions (§1, §2, §5): the how-to-work rules and the Categorization workflow live in `AGENTS.md`; `CLAUDE.md` is the one-line `@AGENTS.md` import. The export's first line reads exactly `Categorization request: follow the Categorization workflow in AGENTS.md.`
- Access list (§0, §3): the DB holds the allowed sign-in emails (trimmed, lowercased, exactly one @), managed only by `sonar allow-email EMAIL`, `revoke-email EMAIL`, `list-emails` and `sync-emails EMAIL...` (replaces the list, needs at least one); every `sonar` command reads its DB from `--db`, else `SONAR_DB_PATH`, else `data/sonar.db`.
- Sign-in (§0, §3): when SONAR_GOOGLE_CLIENT_ID, SONAR_GOOGLE_CLIENT_SECRET, SONAR_SESSION_SECRET and SONAR_BASE_URL are all set, every page and API call needs a Google sign-in with a verified email on the access list, checked on every request; signed out, pages go to /auth/login and the API answers 401; a listed-out email gets a not-allowed page (API 403); none set = no sign-in; some set = `sonar` refuses to start. The server port is SONAR_PORT, else 8000.
- API token (§13 Categorization API, Sign-in): with sign-in on and SONAR_API_TOKEN set, /api/* also accepts `Authorization: Bearer <token>`; a wrong token answers 401; pages never accept it.
- Debt categories (§5, §7): a `fixed` category can be flagged as loans and installments (Categories page, API `debt`); only `fixed` categories may hold the flag; migration 0008 flags the seeded Loans & Installments category; edits without `debt` and `import-categories` keep the flag of a surviving `fixed` category.
- Draft debts (§6, §7): each active detected recurring payment in a debt category that no debt links to yet gets one draft debt, shown as needs details on the Debts page and prefilled with the payment's name, its latest amount as the rate, its interval, the earliest matching debit as the first payment and a match rule (the mandate reference for mandate-keyed payments, else the latest debit's counterparty); an open draft disappears when its payment stops qualifying; completing it as an installment or loan creates an ordinary debt, and that payment never gets a draft again, even if the debt is deleted later.
- Recurring income (§6, §9): credits (amount above 0) in `income` categories are detected as recurring series with the same grouping, interval evidence, stale-series drop, typical day, latest amount and next due date as outgoing payments; credits in any other category or uncategorized, and debits, are ignored. The salary series is excluded: a series whose typical day is within 7 days of the salary day, counted across the month end as min(|a−b|, 31−|a−b|), is the salary (distance 7 is excluded, 8 is kept). Income series are detected on the fly from the transactions and are not stored. Forecast (§9): each income series' occurrences inside the window [estimate date + 1, payday − 1] are inflows, named by their category and counted at the series' latest amount, except an occurrence already booked within 7 days of it (the rule for fixed payments); worst and best both rise by the inflow total, and expected = balance + inflows − due − expected Keep the lights on. Income series are not fixed payments: they stay off the Fixed payments page and out of fixed costs and due.
