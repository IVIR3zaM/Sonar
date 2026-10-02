# Sonar

A local-first household finance dashboard. Sonar imports bank CSV exports, categorizes transactions, detects recurring payments, tracks installments and loans, and forecasts whether the balance will last until the next payday.

It runs on your own machine (`127.0.0.1`), keeps everything in a local SQLite file, and never talks to your bank or any other service.

## Features

- **Import:** upload one or more bank exports at once. Each format is detected automatically and duplicates are skipped. Supported today: the Deutsche Bank current account (Girokonto) CSV.
- **Categorization:** ordered rules (first match wins) on counterparty or purpose text, amount sign and range, IBAN or creditor ID. Rules are re-applied to every stored transaction whenever they change.
- **Recurring payments:** detects fixed costs that repeat every 1, 2, 3, 6 or 12 months, using mandate reference, creditor ID or counterparty.
- **Installments and loans:** tracks what has been paid, what remains and the payoff date, linked to the real bank payments.
- **Dashboard:** a traffic light for the projected balance on the day before payday, shown as a worst-to-best range. Below it: fixed payments still due, a forecast for variable spending, fixed costs per month for the next 12 months, and debts remaining.
- **Monthly spending** by salary month, a **Keep the lights on** view of reducible everyday spending, and an **Uncategorized** page.

## Quick start

Requires [uv](https://docs.astral.sh/uv/) and Python 3.12.

```bash
uv sync
uv run sonar
```

Open <http://127.0.0.1:8000>, import an export, then set your salary day and current balance under Settings. Your data lives in `data/sonar.db`, which is gitignored.

## Categorizing with Claude Code

Sonar has no rule editor in the UI. You manage categories and rules by talking to [Claude Code](https://claude.com/claude-code):

1. On the Uncategorized page, copy the export block and paste it into Claude Code in this repository.
2. Claude reads the current categories, rules and uncategorized transactions through the local JSON API (`/api/categories`, `/api/rules`, `/api/uncategorized`).
3. It proposes changes, and once you confirm, writes them through the same API.

Rules live only in your local database, so personal names, IBANs and creditor IDs never end up in the repository. The full workflow is in [AGENTS.md](AGENTS.md).

## Development

```bash
uv run pytest                 # tests
uv run ruff check .           # lint
uv run ruff format --check .  # formatting
TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o src/sonar/web/static/sonar.css --minify  # rebuild CSS after template changes
```

Stack: FastAPI, Jinja2 and HTMX, SQLite with plain SQL and numbered migrations, and Tailwind CSS v4 (prebuilt, so running the app needs no build step). Money is stored as integer cents.

- [SPEC.md](SPEC.md) describes the intended behavior.
- [AGENTS.md](AGENTS.md) holds the engineering rules and the plan-driven workflow: a planner, executor and verifier agent build each change test-first.

### Adding a bank format

Add one module under `src/sonar/importing/importers/` with `NAME`, `detect` and `parse` (plus an optional `parse_balance`), register it in `IMPORTERS`, and add fixture tests with anonymized data.

## License

Copyright 2026 Reza Maghoul. Licensed under the [Apache License, Version 2.0](LICENSE).
