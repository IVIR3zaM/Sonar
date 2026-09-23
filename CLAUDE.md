# Sonar

A local household finance dashboard for importing bank exports, categorizing transactions, detecting recurring payments, and forecasting cash flow to payday. Runs on `127.0.0.1` with no authentication. Python 3.12 with FastAPI, SQLite, Jinja2 templates and HTMX. Build brief: SPEC.md.

## Setup

```bash
uv sync              # Install dependencies
uv run sonar         # Start the app (http://127.0.0.1:8000)
uv run pytest        # Run tests
uv run ruff check .  # Check style and lint
uv run ruff format --check .  # Check formatting
```

## Layout

- `src/sonar/`: main package
- `src/sonar/migrations/`: numbered SQL files (NNNN_*.sql), applied at startup
- `src/sonar/templates/`: Jinja2 templates
- `tests/`: pytest tests
- `data/`: SQLite database, gitignored
- `samples/`: real bank exports, gitignored, never used in tests

## Orchestrator workflow

SPEC.md §1 and §2 are the source of truth. Workflow state in `.plan/state.md`. Agent definitions in `.claude/agents/`: Orchestrator (main session), Planner, Executor, Verifier. Each agent has one strict output format. Maximum 2 replans per milestone; human checkpoint after the first plan, if the sample export is missing, after 2 failed replans, or if the spec is ambiguous.

## Categorization workflow

(filled in M2, see SPEC §5)
