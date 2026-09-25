# Sonar

A local household finance dashboard for importing bank exports, categorizing transactions, detecting recurring payments, and forecasting cash flow to payday. Runs on `127.0.0.1` with no authentication. Python 3.12 with FastAPI, SQLite, Jinja2 templates and HTMX.

- **What to build:** `SPEC.md`, the source of truth for behavior. Cite it as `SPEC §n`; §13 amendments override earlier sections.
- **How to work:** this file.

## Setup

```bash
uv sync              # Install dependencies
TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/static/src/app.css -o src/sonar/static/sonar.css --minify  # Build CSS
uv run sonar         # Start the app (http://127.0.0.1:8000)
uv run pytest        # Run tests
uv run ruff check .  # Check style and lint
uv run ruff format --check .  # Check formatting
uv run sonar import-categories data/categories.toml  # One-off: load the owner's local rules into the DB
```

## Layout

- `src/sonar/`: main package
- `src/sonar/migrations/`: numbered SQL files (NNNN_*.sql), applied at startup
- `src/sonar/templates/`: Jinja2 templates; `components/` holds the macros
- `src/sonar/importers/`: one module per bank format (NAME, detect, parse, optional parse_balance), registered in IMPORTERS; a new source = one importer module + fixture tests
- `tests/`: pytest tests; `tests/html.py` holds the page-test helpers
- `data/`: SQLite database, gitignored
- `samples/`: real bank exports, gitignored, never used in tests
- `.plan/`: one file per plan, `YYYY-MM-DD-<slug>.md`, holding its graph and its state
- `.claude/agents/`: planner, executor, verifier. `.claude/skills/`: new-plan, run-plan

## Engineering rules (the Verifier enforces these)

- **Strict TDD.** Every task starts with a failing test, then the minimal code to pass it, then a refactor. No behavior without a test.
- **KISS and YAGNI.** Add an abstraction only when it has at least 2 real uses or a concrete need in SPEC. A design pattern must pay for its complexity; the importer registry is the known case that does.
- **Readable by a human.** Code reads top-down like prose. Small functions, domain names (`booking_date`, `next_due_date`), type hints. Comments explain *why*, never *what*.
- **Functional core, thin shell.** Parsing, dedup, categorization, recurrence detection and forecasting are pure functions over plain dataclasses; the database and web layers call them. `today` is always a parameter; domain code never calls `date.today()`.
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

## Token discipline (every session and every agent)

- No prose, narration, restated tasks or summaries of intent. Replies use the exact formats of the agent files.
- Between agents, pass paths and `file:line`, never file contents.
- Read only what the task needs: Grep, then Read with offset/limit. Never read `uv.lock`, `sonar.css`, `static/vendor/`, finished plans, or a sample in full.
- The orchestrator's context stays near-empty. It reads the plan's head only, never briefs, diffs, source or test output.
- Pick the cheapest model that does the job well. Agent files stay at most 25 lines; this file is loaded by every agent, so keep it short.

## Graph workflow

Every code change goes through a plan. The exceptions are the Categorization workflow and edits to docs or workflow files.

1. **Plan:** `/new-plan <request>`. The Planner writes `.plan/<today>-<slug>.md`: a header, the graph table, open questions and one brief per node. The main session shows the graph and waits for approval (`DRAFT` → `READY`).
2. **Run:** `/run-plan [name]`. The main session becomes the Orchestrator. Without a name it suggests the next open plan. It dispatches Executors, then Verifiers, and commits each verified node.
3. **Pause and resume:** the plan file is the only runtime state. Stop at any time; `/run-plan <name>` picks up from the file.

Use these two skills, not the global `graph-plan` skill.

| Role | Runs as | Writes | Default model | Replies with |
|---|---|---|---|---|
| Orchestrator | main session | plan status, commits; never product code | session | ≤ 3 lines to the user per wave |
| Planner | `.claude/agents/planner.md` | `.plan/` only | opus | `PLANNED …`, `REPLANNED …`, `SPLIT …` |
| Executor | `.claude/agents/executor.md` | its node's Write paths only | per node | `DONE N03 \| tests: n passed` or `BLOCKED N03: <reason>` |
| Verifier | `.claude/agents/verifier.md` | nothing | per node | `PASS N03` or `FAIL N03` plus ≤ 5 finding bullets |

**Graph rules**

- One node is one coherent change that one executor finishes in one context, starting with a failing test. If its Read and Write paths can't be named, split it.
- Dependencies are explicit edges. Nodes that may run in the same wave have disjoint Write paths.
- Briefs are self-contained: Do, Read, Write, Test first, and numbered, falsifiable Done-when criteria (C1, C2, …). Cite `SPEC §n` and `file:line`; don't paste.
- Verification is a phase of every exec node. Nothing starts on unverified work, and no agent verifies its own work.
- Every attempt is a fresh agent. The node's Findings in the plan are the only thing that carries over.
- A retry fixes the work (Verifier FAIL). A replan fixes the brief (Executor BLOCKED, the same criterion failing twice, or tries used up). The human fixes the plan (replans used up).
- Budgets per node: 2 tries per brief, 2 replans. Then the node is BLOCKED: tell the user and keep running the nodes that don't depend on it.
- The orchestrator writes a node's status before dispatching it. Each verified node is one commit, the checkpoint a replan resets to.
- Every plan ends with a `check` node for the whole plan: verify command, SPEC §11, and the SPEC §12 UI acceptance when templates changed.

**Model selection:** the Planner suggests one per node (`exec/verify`); the orchestrator decides.

- haiku: mechanical work (fixtures, config, renames, simple templates) and verifying it.
- sonnet: well-specified implementation and routine verification.
- opus: planning and replanning; tricky logic (dedup, recurrence, schedule periods, forecasting) and verifying it.

**Human checkpoints:** after a plan is written; when a plan has open questions (one question each, with a recommended answer); at `gate` nodes that need the user; when a node is BLOCKED; when a node needs `samples/` and it is empty.

## Categorization workflow

Categories and rules live only in the DB (N11); nothing here edits a file.

1. **Trigger:** a pasted export starting with `HEADER` (`uncategorized_export.py:21`), or an owner request to categorize.
2. **Use the running app:** `curl -s http://127.0.0.1:8000/api/categories`; if it doesn't answer, start `uv run sonar` in the background (stop it at the end if you started it).
3. **Read:** `GET /api/categories`, `GET /api/rules`, `GET /api/uncategorized`.
4. **Propose:** the exact category adds/edits/removes and rule adds/edits/removes (category name and group; rule fields and position; first match wins). Ask the owner to confirm. Write nothing before confirmation.
5. **Write:** after confirmation, call the endpoints below with `curl -s -X POST -H 'Content-Type: application/json' -d '{...}' ...` (PUT/DELETE the same way). Stop and report on any 4xx. Every write re-applies rules and re-runs recurring detection.
6. **Reply** in at most 5 lines: the changes made and the uncategorized count before and after.
7. Edit no repo file, add no tests for rules, never write real names, IBANs or creditor IDs into a tracked file (they live only in the local DB). Handle it in the main session, without the agent graph.

Endpoints (all under `/api`, `Content-Type: application/json`):

| Method | Path | Body fields |
|---|---|---|
| GET | `/categories` | - |
| POST | `/categories` | `name`, `group` |
| PUT | `/categories/{id}` | `name`, `group` |
| DELETE | `/categories/{id}` | - |
| GET | `/rules` | - |
| POST | `/rules` | `category`, `counterparty`, `counterparty_regex`, `purpose`, `purpose_regex`, `sign`, `iban`, `creditor_id`, `min_amount`, `max_amount`, `position` |
| PUT | `/rules/{id}` | same fields as POST `/rules` |
| DELETE | `/rules/{id}` | - |
| POST | `/rules/{id}/move` | `position` |
| GET | `/uncategorized` | - |

The five `group` values, and what each means for the forecast:

- `income`: money earned; not spending.
- `transfer`: money moved between the owner's own accounts; not spending.
- `fixed`: recurring and hard to change (the dashboard's Fixed costs forecast).
- `lights_on`: reducible but never zero -- groceries, transport, shopping (the Keep the lights on page).
- `occasional`: one-off spending -- fees, education, donations, health, dining and similar.
