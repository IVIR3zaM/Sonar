# Household Finance Dashboard: Build Brief

You are starting in a folder that contains only a real Deutsche Bank CSV export (and possibly this brief). Do these three things before anything else:

1. Save this brief unchanged as `SPEC.md`. It is the source of truth for every agent.
2. Move the CSV into `samples/` and add `samples/` to `.gitignore` before the first commit. Real bank data must never be committed.
3. Set up the agent workflow (section 1) and run it.

## 0. What we're building

A local web app for our household. It imports bank exports, categorizes transactions, detects fixed costs, tracks installments and loans, and forecasts whether we'll get through to the next salary day.

- Runs locally only (bind 127.0.0.1). No auth for now.
- Data comes in by file upload for now. A live bank connection (Enable Banking or FinTS) may come later. Don't build it, but don't design anything that blocks it.

## 1. How you work: orchestrated agent graph

### Roles

- **Orchestrator**: this main session. It never writes product code. It reads state, picks models, dispatches work, commits, and talks to me.
- **Planner**, **Executor**, **Verifier**: subagents defined in `.claude/agents/planner.md`, `executor.md` and `verifier.md`. Subagents can't spawn subagents, which is why the orchestrator must be the main session.
  - Each agent file is at most 25 lines. It states the role, its exact output format (below), and which SPEC.md sections to read.
  - Planner: read-only tools (Read, Grep, Glob). Default model: opus.
  - Executor: edit tools and Bash. Default model: sonnet.
  - Verifier: Read, Grep, Glob and Bash. It runs tests and lint but never edits. Default model: sonnet.

### Loop per milestone

1. The orchestrator reads `.plan/state.md`, `git log --oneline -5` and the test status. If `.plan/state.md` is missing, it creates it.
2. The Planner receives the milestone goal, the relevant SPEC section numbers and the current state. It returns a task graph.
3. The orchestrator dispatches tasks in dependency order. Independent tasks that touch disjoint files may run in parallel. Everything else runs sequentially.
4. The Verifier checks the milestone against SPEC and section 2.
   - **PASS**: the orchestrator commits, updates the state file and moves to the next milestone.
   - **FAIL**: the orchestrator sends the Verifier's findings to the Planner, which replans only the failing parts. Then execution and verification run again.
5. The maximum is **2 replans per milestone**. If verification fails after the 2nd replan, stop, report the findings to me in at most 10 lines, and wait.

### Model selection

The orchestrator decides the model for every Agent call, using the Agent tool's `model` parameter. The Planner suggests a model per task, and the orchestrator makes the final call. Always pick the cheapest model that will do the task well.

- **haiku**: mechanical work, such as fixtures, config, renames and simple templates.
- **sonnet**: the default for well-specified implementation tasks and routine verification.
- **opus**: planning and replanning; tricky logic (dedup, recurrence detection, schedule periods, forecasting); verifying the milestones that contain that logic.

### Token discipline (applies to all agents)

- No prose, no restating the task, no narration, no summaries of intent.
- Between agents, pass file paths and line references, never file contents.
- Each agent reads only the files its task needs.
- Output formats are hard limits:
  - **Planner**:
    ```
    M<n> <goal>
    T1 [sonnet] <imperative task> | files: a.py,test_a.py | test first: <behavior> | deps: -
    T2 [opus] ... | deps: T1
    ```
  - **Executor**: `DONE|BLOCKED T<n> | files: ... | tests: <n> passed`, plus one line of reason if blocked.
  - **Verifier**: `PASS`, or `FAIL` followed by at most 8 bullets of the form `path:line - problem - expected`.
- `.plan/state.md` is at most 40 lines: current milestone, task statuses, replan count and open questions. A fresh session must be able to resume from it alone.

### Human checkpoints

Stop and wait for me only in these cases:

- After the first plan: show the milestone list and the M1 tasks in at most 25 lines.
- If no sample export is in `samples/`, ask me for it before planning M1.
- After 2 failed replans.
- When the spec is ambiguous in a way that changes behavior. Ask one question and include your recommended answer.

## 2. Engineering rules (the Verifier enforces these)

- **Strict TDD.** Every task starts with a failing test, then the minimal code to pass it, then a refactor. The Verifier rejects any behavior that has no test.
- **KISS and YAGNI.** Add an abstraction only when it has at least 2 real uses or a concrete need in this spec. A design pattern must pay for the complexity it adds. The importer registry (section 4) is the one known case that does.
- **Readable by a human.** Code reads top-down like prose. Use small functions, domain names (`booking_date`, `next_due_date`) and type hints. Comments explain *why*, never *what*.
- **Functional core, thin shell.** Parsing, dedup, categorization, recurrence detection and forecasting are pure functions over plain dataclasses. The database and web layers call them. `today` is always a parameter; domain code never calls `date.today()`.
- **Money and dates.** Money is integer cents, never float. Dates are `datetime.date`.
- **Tests.** Use pytest. Tests are fast and never touch the network. Fixtures are anonymized; real data never goes in tests.
- **Lint and commits.** ruff lint and format must be clean. The orchestrator commits after each verified milestone.

## 3. Stack (already decided)

- Python 3.12 with uv.
- FastAPI with server-rendered Jinja2 pages and HTMX for small interactions. No SPA, no JS build step.
- SQLite via stdlib `sqlite3` with plain SQL. No ORM.
- pytest and ruff.

Why this stack: Python has the best tooling for CSV and PDF parsing (pdfplumber later) and for German banking (python-fints, Enable Banking examples), and this is the fewest moving parts for a local app.

Additional setup:

- Schema changes go in numbered SQL migration files, applied at startup and tracked in a table. Hand-entered data (payment schedules, debts, settings) must survive upgrades.
- Run `git init` at the start. `data/` (the database) and `samples/` (real exports) are gitignored.
- The app starts with one command.

## 4. Import

- I can upload one or more files at once. For each file, show: the format detected, rows added, rows skipped as duplicates, and rows left uncategorized.
- **Format detection.** Each source format is one importer module implementing `detect(file) -> bool` and `parse(file) -> list[ParsedTransaction]`, registered in a single list. The app picks the importer whose `detect` matches. If none matches, show a clear error listing the supported formats. Adding a source must mean one new module plus its fixture tests, and no other changes.
- **Build now: the Deutsche Bank current account (Girokonto) CSV.**
  - Do not rely on memory for its layout. Derive the parser from the real export in `samples/`, and create an anonymized fixture from it for the tests.
  - To save tokens, agents read only the preamble, the header, a few rows and the last lines of the sample, never the whole file. Record the confirmed layout (columns, encoding, separators, preamble and footer) in a short comment at the top of the importer module.
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
  - Rules are ordered and the first match wins. A rule matches on counterparty or purpose text (case-insensitive substring or regex), optionally combined with amount sign, IBAN or creditor ID.
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

The Planner refines these into tasks. Each milestone must end in a usable state: I can start the app and click through everything built so far.

- **M0 Skeleton:** uv project, ruff, pytest, FastAPI hello page, migration runner, `CLAUDE.md`, `.claude/agents/`, `.gitignore`, `.plan/state.md`.
- **M1 Import:** importer registry, Deutsche Bank CSV importer built from the sample in `samples/`, idempotent storage, upload page with results. Importing the real sample must succeed.
- **M2 Categorization:** `categories.toml` with the initial taxonomy, rule engine, re-apply, Uncategorized export, the Categorization workflow in `CLAUDE.md`.
- **M3 Recurring payments:** detection, schedule periods, and the UI to edit, pause, resume, dismiss and add payments.
- **M4 Installments and loans.**
- **M5 Forecast, dashboard and settings.**

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

**Start now:** set up M0, have the Planner produce the milestone plan, then stop at the first checkpoint.
