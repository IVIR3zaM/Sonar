# Sonar

A local household finance dashboard for importing bank exports, categorizing transactions, detecting recurring payments, and forecasting cash flow to payday. Runs on `127.0.0.1`; Google sign-in is optional (SPEC §13 Sign-in). Python 3.12 with FastAPI, SQLite, Jinja2 templates and HTMX.

- **What to build:** `SPEC.md`, the source of truth for behavior. Cite it as `SPEC §n`; §13 amendments override earlier sections.
- **How to work:** this file.

## Setup

```bash
uv sync              # Install dependencies
TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o src/sonar/web/static/sonar.css --minify  # Build CSS
uv run sonar         # Start the app (http://127.0.0.1:8000)
./run.sh  # Start with the settings in .env (see .env.example)
uv run pytest        # Run tests
uv run ruff check .  # Check style and lint
uv run ruff format --check .  # Check formatting
uv run sonar import-categories data/categories.toml  # One-off: load the owner's local rules into the DB
```

## Layout

- `src/sonar/<feature>/`: one package per feature (`importing`, `categorization`, `recurring`, `debts`, `cashflow`). Pure logic has a domain name (`detect.py`, `forecast.py`); `store.py` is the only DB access; `service.py` coordinates several stores.
- `src/sonar/web/`: `app.py` wires only; `pages/` has one router per page; `api/` (one module per area); `templates/` (`components/` holds the macros); `static/`
- `src/sonar/importing/importers/`: one module per bank format (NAME, detect, parse, optional parse_balance), registered in IMPORTERS; a new source = one importer module + fixture tests
- `src/sonar/`: top level holds only `__main__`, `db`, `money`, `transactions`, `migrations/`
- `tests/`: follows `src/sonar/`'s layout (`tests/<feature>/`, `tests/web/`); `tests/html.py` holds the page-test helpers
- `data/`: SQLite database, gitignored
- `samples/`: real bank exports, gitignored, never used in tests
- `.plan/`: Planzilla plans. `.planzilla/`, `.agents/`, `.claude/agents/plz-*`, `.claude/skills/plz-*`: vendored Planzilla, never hand-edited

## Engineering rules (the Verifier enforces these)

- **Strict TDD.** Every task starts with a failing test, then the minimal code to pass it, then a refactor. No behavior without a test.
- **KISS and YAGNI.** Add an abstraction only when it has at least 2 real uses or a concrete need in SPEC. A design pattern must pay for its complexity; the importer registry is the known case that does.
- **Readable by a human.** Code reads top-down like prose. Small functions, domain names (`booking_date`, `next_due_date`), type hints. Comments explain *why*, never *what*.
- **Functional core, thin shell.** Parsing, dedup, categorization, recurrence detection and forecasting are pure functions over plain dataclasses; the database and web layers call them. `today` is always a parameter; domain code never calls `date.today()`.
- **Structure.** New code goes in an existing feature package; a new package needs a SPEC feature behind it. One concept has one name: its pure part and its store sit side by side, never as `x` / `x_ing` / `x_store` at the top level. A page's routes go in `web/pages/<page>.py`, never in `app.py`. `tests/test_architecture.py` enforces the import rules.
- **Money and dates.** Money is integer cents, never float. Dates are `datetime.date`.
- **Tests.** pytest, fast, no network. Fixtures are anonymized; real data never goes in tests.
- **Lint.** `ruff check` and `ruff format --check` are clean.
- **Always usable.** Every finished plan leaves the app startable with one command and every built page working.

## Conventions

- **Migrations:** a schema change is a new `NNNN_*.sql`; never edit an applied one. Hand-entered data (schedules, debts, settings) must survive upgrades.
- **Samples:** read only the preamble, header, a few rows and the tail of a file in `samples/`, never the whole file.
- **Smoke runs** use a temp DB, never `data/sonar.db`. The starlette/httpx deprecation warning is harmless.
- **UI:** pages extend `base.html`, compose the `components/` macros, and have no inline `<style>`. Displayed amounts use `eur`, form prefills use `money`, and dates use `date`. Never hand-edit `sonar.css`: rebuild it after any template or CSS change and commit it.
- **Page tests** assert on stable hooks (ids, `data-*`) through `tests/html.py`, never on CSS classes. Pure CSS classes need no test.
- **Visual check:** a plan that changes templates ends with a `gate` node. The orchestrator starts the app on a temp DB, imports the real sample, sets salary day and balance, and checks every changed page in the browser pane at desktop and 375px, light and dark (read_page first, scaled screenshots only where layout matters).
- **Instructions:** edit AGENTS.md only; CLAUDE.md is the one-line `@AGENTS.md` import.

## Token discipline (every session and every agent)

- No prose, narration, restated tasks or summaries of intent. Replies use the exact formats of the role files.
- Between agents, pass paths and `file:line`, never file contents.
- Read only what the task needs: Grep, then Read with offset/limit. Never read `uv.lock`, `sonar.css`, `static/vendor/`, finished plans, or a sample in full.
- The orchestrator's context stays near-empty. It reads the plan's head only, never briefs, diffs, source or test output.
- Pick the cheapest model that does the job well. This file is loaded by every agent, so keep it short.

## Planzilla workflow

Every code change goes through a plan. The exceptions are the Categorization workflow and edits to docs or workflow files. Planzilla is vendored in `.planzilla/` (never edit it; upgrade with `planzilla install`); its rules are in the Planzilla section at the end of this file.

1. **Plan:** `/plz-new-plan <request>`. Plans live in `.plan/`; show the graph and wait for approval.
2. **Run:** `/plz-run-plan [slug]`. Dispatches executors and verifiers, one commit per verified node.
3. **Pause and resume:** plan state is the only runtime state; `/plz-run-plan <slug>` resumes.

Sonar's rules above (TDD, structure, visual check, `check` node with SPEC §11 and §12) go into the plans' criteria.

**Human checkpoints:** after a plan is written; when a plan has open questions (one question each, with a recommended answer); at `gate` nodes that need the user; when a node is BLOCKED; when a node needs `samples/` and it is empty.

## Categorization workflow

Categories and rules live only in the DB (N11); nothing here edits a file.

1. **Trigger:** a pasted export starting with `HEADER` (`categorization/export.py:21`), or an owner request to categorize.
2. **Use the running app:** `curl -s http://127.0.0.1:8000/api/categories`; if it doesn't answer, start `uv run sonar` in the background (stop it at the end if you started it). When sign-in is on, every curl below also adds `-H "Authorization: Bearer $SONAR_API_TOKEN"`.
3. **Read:** `GET /api/categories`, `GET /api/rules`, `GET /api/uncategorized`.
4. **Propose:** the exact category adds/edits/removes and rule adds/edits/removes (category name and group; rule fields and position; first match wins). Ask the owner to confirm. Write nothing before confirmation.
5. **Write:** after confirmation, call the endpoints below with `curl -s -X POST -H 'Content-Type: application/json' -d '{...}' ...` (PUT/DELETE the same way). With sign-in on, add `-H "Authorization: Bearer $SONAR_API_TOKEN"` to every call. Stop and report on any 4xx. Every write re-applies rules and re-runs recurring detection.
6. **Reply** in at most 5 lines: the changes made and the uncategorized count before and after.
7. Edit no repo file, add no tests for rules, never write real names, IBANs or creditor IDs into a tracked file (they live only in the local DB). Handle it in the main session, without the agent graph.

Endpoints (all under `/api`, `Content-Type: application/json`):

| Method | Path | Body fields |
|---|---|---|
| GET | `/categories` | - |
| POST | `/categories` | `name`, `group`, `debt` |
| PUT | `/categories/{id}` | `name`, `group`, `debt` |
| DELETE | `/categories/{id}` | - |
| GET | `/rules` | - |
| POST | `/rules` | `category`, `counterparty`, `counterparty_regex`, `purpose`, `purpose_regex`, `sign`, `iban`, `creditor_id`, `min_amount`, `max_amount`, `position` |
| PUT | `/rules/{id}` | same fields as POST `/rules` |
| DELETE | `/rules/{id}` | - |
| POST | `/rules/{id}/move` | `position` |
| GET | `/uncategorized` | - |
| GET | `/recurring` | - |
| POST | `/recurring` | `name`, `amount_cents`, `interval_months`, `day`, `starts_on`, `description` |
| PUT | `/recurring/{id}` | `name`, `description`, `amount_cents`, `interval_months`, `day` |
| POST | `/recurring/{id}/pause` | `last_date` |
| POST | `/recurring/{id}/resume` | `starts_on`, `amount_cents`, `interval_months`, `day` |
| POST | `/recurring/{id}/dismiss` | - |
| POST | `/recurring/{id}/restore` | - |
| GET | `/debts` | - |
| POST | `/debts` | `kind` plus the installment or loan fields above; `match_field` is `counterparty`, `mandate` or `purpose` |
| PUT | `/debts/{id}` | same fields as POST `/debts` |
| DELETE | `/debts/{id}` | - |
| GET | `/debts/drafts` | - |
| POST | `/debts/drafts/{id}` | same fields as POST `/debts` |
| GET | `/settings` | - |
| PUT | `/settings` | `salary_day`, `overdraft_limit_cents` |
| POST | `/settings/balance` | `amount_cents`, `as_of` |
| POST | `/reapply` | - |
| GET | `/dashboard` | - |
| GET | `/lights-on` | - |
| GET | `/monthly` | query `month`, `category` |
| GET | `/transactions` | query `from`, `to`, `category`, `uncategorized`, `q` |

The five `group` values, and what each means for the forecast:

- `income`: money earned; not spending.
- `transfer`: money moved between the owner's own accounts; not spending.
- `fixed`: recurring and hard to change (the dashboard's Fixed costs forecast).
- `lights_on`: reducible but never zero -- groceries, transport, shopping (the Keep the lights on page).
- `occasional`: one-off spending -- fees, education, donations, health, dining and similar.

`debt: true` marks a `fixed` category as loans and installments; its recurring payments become draft debts on the Debts page.

<!-- planzilla:begin -->
## Planzilla

This repo plans its work with Planzilla. Plans live in `.plan/`.

- Never read or edit plan state by hand. Use only the CLI `.planzilla/plz`; `.planzilla/plz --help` lists the commands.
- To plan a task, follow the skill `plz-new-plan`: `.agents/skills/plz-new-plan/SKILL.md`.
- To run a plan, follow the skill `plz-run-plan`: `.agents/skills/plz-run-plan/SKILL.md`.
- The same skills are in `.claude/skills/`.
- Subagents follow the role prompt for their job:
  - `.planzilla/roles/planner.md`
  - `.planzilla/roles/executor.md`
  - `.planzilla/roles/verifier.md`
  - `.planzilla/roles/visual.md`
- `.planzilla/` is vendored. Never edit it; upgrade by re-running `planzilla install`.
<!-- planzilla:end -->
