# Sonar

A local household finance dashboard for importing bank exports, categorizing transactions, detecting recurring payments, and forecasting cash flow to payday. Runs on `127.0.0.1` with no authentication. Python 3.12 with FastAPI, SQLite, Jinja2 templates and HTMX. Build brief: SPEC.md.

## Setup

```bash
uv sync              # Install dependencies
TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/static/src/app.css -o src/sonar/static/sonar.css --minify  # Build CSS
uv run sonar         # Start the app (http://127.0.0.1:8000)
uv run pytest        # Run tests
uv run ruff check .  # Check style and lint
uv run ruff format --check .  # Check formatting
```

## Layout

- `src/sonar/`: main package
- `src/sonar/migrations/`: numbered SQL files (NNNN_*.sql), applied at startup
- `src/sonar/templates/`: Jinja2 templates
- `src/sonar/importers/`: one module per bank format (NAME, detect, parse, optional parse_balance), registered in IMPORTERS; a new source = one importer module + fixture tests
- `tests/`: pytest tests
- `data/`: SQLite database, gitignored
- `samples/`: real bank exports, gitignored, never used in tests

## Orchestrator workflow

SPEC.md §1 and §2 are the source of truth. To resume work, read `.plan/state.md` first and follow its Resume steps; task text lives in `.plan/plan.md`. Agent definitions in `.claude/agents/`: Orchestrator (main session), Planner, Executor, Verifier. Each agent has one strict output format. Maximum 2 replans per milestone; human checkpoint after the first plan, if the sample export is missing, after 2 failed replans, or if the spec is ambiguous.

## Categorization workflow

1. Edit `src/sonar/categories.toml`: add or extend categories (income/fixed/variable/transfer) and ordered rules.
2. Rules match on counterparty or purpose text (case-insensitive substring or regex), optionally with amount sign, absolute amount range, IBAN, or creditor ID; first match wins.
3. Add one test case per new rule to `tests/test_rules_table.py` with fake strings around the matched keyword.
4. Rules may use real counterparty names and IBANs (the owner's choice); tests never do, they use fake strings.
5. Run `uv run pytest` and touch nothing else.
6. Reply in at most 5 lines listing the new rules.
7. Handle it directly in the main session, without the agent graph.
