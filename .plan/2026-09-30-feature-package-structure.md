# Feature package structure
status: DONE
created: 2026-09-30 · updated: 2026-09-30
goal: src/sonar split into feature packages (importing, categorization, recurring, debts, cashflow) and web/ (pages/ routers), tests mirrored, import rules enforced by tests/test_architecture.py; no behavior change; collected tests = count at 132cabf (last commit before this plan) + tests/test_architecture.py
request: owner request 2026-09-30 (feature name `cashflow`): restructure src/sonar into feature packages, architecture test first, docs updated
spec: SPEC §2, §11, §12 (UI acceptance: CSS rebuild unchanged)
verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
budgets: 2 tries per brief · 2 replans per node

## Graph

| id | title | type | deps | model | try | rp | status | note |
|----|-------|------|------|-------|-----|----|--------|------|
| N01 | architecture test (xfail) | exec | - | sonnet/sonnet | 1 | 0 | DONE | |
| N02 | MIGRATIONS_DIR in db.py, tests/migrations | exec | - | haiku/haiku | 1 | 0 | DONE | |
| N03 | importing package | exec | N01,N02 | sonnet/haiku | 1 | 0 | DONE | |
| N04 | categorization package | exec | N03 | sonnet/sonnet | 1 | 0 | DONE | |
| N05 | recurring package | exec | N04 | sonnet/haiku | 1 | 0 | DONE | |
| N06 | debts package | exec | N05 | sonnet/haiku | 1 | 0 | DONE | |
| N07 | cashflow package | exec | N06 | sonnet/haiku | 1 | 0 | DONE | |
| N08 | web package, templates and static | exec | N07 | sonnet/sonnet | 1 | 0 | DONE | |
| N09 | page routers: dashboard, monthly, lights_on, uncategorized, import_ | exec | N08 | sonnet/sonnet | 1 | 0 | DONE | |
| N10 | page routers: recurring, debts, settings, categories; forms.py | exec | N09 | sonnet/sonnet | 1 | 0 | DONE | |
| N11 | docs: CLAUDE.md, planner.md, SPEC paths | exec | N08 | haiku/haiku | 1 | 0 | DONE | |
| N12 | visual check | gate | N10,N11 | - | 0 | 0 | DONE | |
| N13 | plan acceptance | check | N01,N02,N03,N04,N05,N06,N07,N08,N09,N10,N11,N12 | -/sonnet | 1 | 1 | DONE | |

## Open questions

- none (Q1 answered 2026-09-30: rule 3 exempts only `src/sonar/__main__.py`, the entry point that wires the app for uvicorn, tests/test_main.py:24)

## Nodes

### N01 architecture test (xfail)
Do: Add tests/test_architecture.py: ast-based checks over src/sonar in the style of tests/test_templates_hygiene.py (scan helper plus synthetic `tmp_path` sanity tests, tests/test_templates_hygiene.py:95-121). Each rule is a pure function `<rule>_offenders(root: Path) -> list[str]` returning sorted `"rel/path.py: detail"` strings; the real-tree test asserts the list is empty and prints it on failure. Rules: (1) only `db.py`, `<pkg>/store.py`, `<pkg>/service.py` and files under `web/` import `sqlite3`; (2) only files under `web/` import `fastapi`, `starlette` or `jinja2` (first dotted part); (3) no file outside `web/` imports `sonar.web` or anything below it, including `from sonar import web`; the one exemption is the top-level `__main__.py` (root-relative path exactly `__main__.py`, per answered Q1: `main()` builds the app with `create_app` and hands it to uvicorn), and a `__main__.py` in any subpackage is not exempt; (4) the only top-level `.py` files in src/sonar are `__init__`, `__main__`, `db`, `money`, `transactions`; (5) `web/app.py` (if it exists) has no route decorators (`@<x>.get/post/put/delete/patch(...)`); the detail is the route path string. Imports count from `Import` and level-0 `ImportFrom` nodes anywhere in the tree (module, and `module.name` for each imported name).
Spec: owner request; CLAUDE.md:37 (functional core, thin shell)
Read: tests/test_templates_hygiene.py
Write: tests/test_architecture.py
Test first: the five real-tree tests run with `--runxfail` fail for rules 1, 2, 4 (e.g. `app.py: sqlite3`, `dashboard.py: sqlite3`, `api.py: fastapi`, top-level `schedule.py`) and pass for rule 3; rule 5 passes trivially while web/app.py doesn't exist.
Done when:
- C1 tests/test_architecture.py has one real-tree test per rule (5) and at least one synthetic `tmp_path` test per rule proving the check reports an offender; rules 1-3 also have a synthetic case proving an allowed location (e.g. `cashflow/store.py` importing sqlite3, `web/app.py` importing fastapi, top-level `__main__.py` importing `sonar.web.app`) is not reported; rule 3 also has a synthetic case proving `cashflow/__main__.py` importing `sonar.web.app` is reported (the exemption covers only the top-level `__main__.py`)
- C2 the real-tree tests for rules 1, 2, 4, 5 carry `@pytest.mark.xfail(strict=False, reason="feature-package moves in progress")`; rule 3 has no marker and passes
- C3 `uv run pytest tests/test_architecture.py --runxfail -q` fails exactly the rule 1, 2 and 4 real-tree tests, and their messages name the current offenders (rule 4 lists e.g. `app.py`, `schedule.py`, `dashboard.py`)
- C4 no file outside tests/test_architecture.py changes
- C5 the verify command exits 0
Findings:
- none

### N02 MIGRATIONS_DIR in db.py, tests/migrations
Do: Move `MIGRATIONS_DIR` from src/sonar/app.py:82 to src/sonar/db.py (same value: the package's `migrations/` dir), so `__main__` gets it from `db`. Replace every test-local `MIGRATIONS_DIR = Path(__file__).parent.parent / "src" / "sonar" / "migrations"` (about 30 files, `rg -n 'MIGRATIONS_DIR = ' tests`, incl. tests/seed.py:17 and tests/test_real_sample.py:24) and every `from sonar.app import MIGRATIONS_DIR` (tests/test_app.py:8, tests/test_recurring_page.py:9, tests/test_recurring_refresh.py:9, tests/test_debt_links_page.py:12) with `from sonar.db import MIGRATIONS_DIR`; drop imports that become unused. `git mv` tests/test_migration_000N.py (N=1..6) to tests/migrations/test_000N.py and add tests/migrations/__init__.py (empty).
Spec: owner request; CLAUDE.md Conventions (Migrations)
Read: src/sonar/db.py, src/sonar/app.py:80-86, src/sonar/__main__.py:10-15
Write: src/sonar/db.py, src/sonar/app.py, src/sonar/__main__.py, tests/** except tests/test_architecture.py
Test first: switch the tests to `from sonar.db import MIGRATIONS_DIR` first; they fail with ImportError until db.py defines it.
Done when:
- C1 `rg -n 'MIGRATIONS_DIR' src` shows exactly one definition, in src/sonar/db.py; src/sonar/app.py and src/sonar/__main__.py import it from `sonar.db`
- C2 `rg -n '"src" / "sonar" / "migrations"' tests` prints nothing
- C3 tests/migrations/ holds test_0001.py … test_0006.py and `__init__.py`; `git status --short` shows the six as renames (`R`)
- C4 `git diff -M HEAD -- tests | rg '^-\s*def test_'` prints nothing (no test removed)
- C5 the verify command exits 0
Findings:
- none

### N03 importing package
Do: Create the `importing` package: `git mv` src/sonar/importers/ → src/sonar/importing/importers/, src/sonar/dedup.py → src/sonar/importing/dedup.py, src/sonar/importing.py → src/sonar/importing/store.py (move importing.py before creating the directory's `__init__.py`; the package and the old module share a name). src/sonar/importing/__init__.py holds a one-line docstring only. Update every import site in src/ and tests/ (`rg -n 'sonar\.(importers|dedup|importing)\b|from sonar import' src tests`; known: src/sonar/app.py:33-34, recurrence.py:17, debts.py:15, uncategorized_export.py:18, the string `"sonar.importing.pick_importer"` at tests/test_importing.py:161), plus docstrings/comments naming the old modules. No alias that reintroduces an old module name. `git mv` tests: test_registry.py, test_deutsche_bank_giro.py, test_dedup.py → tests/importing/ (same names), test_importing.py → tests/importing/test_store.py; add tests/importing/__init__.py; fixture paths become `Path(__file__).parent.parent / "fixtures" / ...` (tests/fixtures/ stays). No other edits.
Spec: owner request; CLAUDE.md Layout (importers)
Read: src/sonar/importing.py:1-20, src/sonar/importers/__init__.py:1-20, tests/test_importing.py:1-20,155-165
Write: src/sonar/importing/**, src/sonar/importers/**, src/sonar/dedup.py, src/sonar/importing.py, src/sonar/{app,recurrence,debts,uncategorized_export}.py, tests/importing/**, tests/test_{registry,deutsche_bank_giro,dedup,importing,real_sample}.py, any other import site rg finds in src/ or tests/
Test first: move the four test files and point their imports at `sonar.importing.*`; they fail with ModuleNotFoundError until the modules move.
Done when:
- C1 src/sonar/importing/ holds `__init__.py`, `dedup.py`, `store.py`, `importers/` (with `__init__.py`, `deutsche_bank_giro.py`); src/sonar/importers/, dedup.py and importing.py are gone
- C2 `git status --short` shows every moved module and test file as a rename (`R`)
- C3 `rg -n --pcre2 'sonar\.(importers|dedup)\b|from sonar\.importing import (?!dedup\b|store\b|importers\b)|"sonar\.importing\.pick_importer"' src tests` prints nothing
- C4 `git diff -M HEAD -- tests | rg '^-\s*def test_'` prints nothing
- C5 `uv run pytest tests/test_architecture.py --runxfail -q` no longer names `dedup.py` or `importing.py` as top-level offenders
- C6 the verify command exits 0
Findings:
- none

### N04 categorization package
Do: Create the `categorization` package with `git mv`: spending_groups.py → categorization/groups.py, categorize.py → categorization/rules.py, uncategorized_export.py → categorization/export.py, taxonomy_store.py → categorization/store.py, taxonomy_service.py → categorization/service.py; then merge src/sonar/categorizing.py into categorization/store.py (append its `_COLUMNS`, `reapply_rules`, `uncategorized_count`, `uncategorized_transactions`, `transactions_with_category`, `_transaction_from_row`; merge imports and the module docstring; names don't collide, src/sonar/taxonomy_store.py:20-306 vs src/sonar/categorizing.py:20-67) and `git rm` categorizing.py. `__init__.py` holds a one-line docstring only. Update every import site and module-style call (`spending_groups.X` → `groups.X`, `taxonomy_store.X` → `store.X`), plus docstrings/comments naming old modules (e.g. src/sonar/api.py:3); no alias that reintroduces an old name. Keep `HEADER` on line 21 of categorization/export.py. `git mv` tests into tests/categorization/: test_spending_groups.py → test_groups.py, test_categorize.py → test_rules.py, test_rules_table.py (same name), test_uncategorized_export.py → test_export.py, test_taxonomy_store.py → test_store.py, test_categorizing.py → test_store_transactions.py, test_taxonomy_service.py → test_service.py; add `__init__.py`. The type-string guard (tests/test_spending_groups.py:51-67) must exempt `categorization/groups.py` by path and still scan all of src/sonar from its new location.
Spec: SPEC §5, §13 (groups); owner request
Read: src/sonar/categorizing.py, src/sonar/taxonomy_store.py:1-60, src/sonar/taxonomy_service.py:1-30, tests/test_spending_groups.py:1-15,51-67
Write: src/sonar/categorization/**, src/sonar/{spending_groups,categorize,uncategorized_export,taxonomy_store,taxonomy_service,categorizing}.py, import sites in src/sonar/{__main__,app,api,dashboard,debt_store,recurring,recurrence,monthly,lights_on}.py and src/sonar/importing/store.py, tests/categorization/**, import sites in tests/ (incl. tests/seed.py, tests/importing/test_store.py, tests/migrations/test_0006.py)
Test first: move the test files and point their imports at `sonar.categorization.*`; they fail with ModuleNotFoundError until the modules move.
Done when:
- C1 src/sonar/categorization/ holds `__init__.py`, `groups.py`, `rules.py`, `export.py`, `store.py`, `service.py`; the six old top-level modules are gone
- C2 `git status --short` shows groups, rules, export, store, service and the seven test files as renames (`R`) and categorizing.py as deleted
- C3 `rg -n 'sonar\.(spending_groups|categorize|categorizing|uncategorized_export|taxonomy_store|taxonomy_service)\b|\b(spending_groups|taxonomy_store)\.' src tests` prints nothing
- C4 every function formerly in categorizing.py is defined once, in categorization/store.py, with an unchanged body
- C5 `sed -n 21p src/sonar/categorization/export.py` starts with `HEADER =`
- C6 `git diff -M HEAD -- tests | rg '^-\s*def test_'` prints nothing
- C7 the type-string guard test (now tests/categorization/test_groups.py) fails if a string such as `"lights_on"` is added to any other module under src/sonar (the verifier checks by reasoning over the code, not by editing)
- C8 the verify command exits 0
Findings:
- none

### N05 recurring package
Do: Create the `recurring` package with `git mv`: schedule.py → recurring/schedule.py, recurrence.py → recurring/detect.py, recurring.py → recurring/store.py (move recurring.py before adding the package `__init__.py`; same name). `__init__.py` holds a one-line docstring only. Update every import site and module-style call (`from sonar import schedule` users: src/sonar/recurrence.py:16, debts.py:14, forecast.py:13; `sonar.recurrence` users: debts.py:16; `sonar.recurring` users: __main__.py, app.py, dashboard.py:21, debt_store.py:25, categorization/service.py; `sonar.schedule` users: amortization.py:14, forecast.py:14, app.py), plus docstrings/comments; no alias that reintroduces an old name. `git mv` tests into tests/recurring/: test_schedule.py (same), test_recurrence.py → test_detect.py, test_recurring.py → test_store.py, test_recurring_sync.py → test_store_sync.py; add `__init__.py`. Page tests (test_recurring_page*.py, test_recurring_refresh.py) stay for N08; only their imports change.
Spec: SPEC §6, §13 (detection); owner request
Read: src/sonar/recurring.py:1-20, src/sonar/recurrence.py:1-20
Write: src/sonar/recurring/**, src/sonar/{schedule,recurrence,recurring}.py, import sites in src/sonar/{__main__,app,dashboard,debt_store,debts,forecast,amortization}.py and src/sonar/categorization/service.py, tests/recurring/**, import sites in tests/
Test first: move the test files and point their imports at `sonar.recurring.*`; they fail with ModuleNotFoundError until the modules move.
Done when:
- C1 src/sonar/recurring/ holds `__init__.py`, `schedule.py`, `detect.py`, `store.py`; src/sonar/schedule.py and recurrence.py are gone
- C2 `git status --short` shows the three modules and four test files as renames (`R`)
- C3 `rg -n --pcre2 'sonar\.(schedule|recurrence)\b|from sonar\.recurring import (?!schedule\b|detect\b|store\b)|from sonar import .*\b(schedule|recurrence|recurring)\b' src tests` prints nothing
- C4 `git diff -M HEAD -- tests | rg '^-\s*def test_'` prints nothing
- C5 the verify command exits 0
Findings:
- none

### N06 debts package
Do: Create the `debts` package with `git mv`: debts.py → debts/model.py (move it before adding the package `__init__.py`; same name), amortization.py → debts/amortization.py, debt_store.py → debts/store.py. `__init__.py` holds a one-line docstring only. Update every import site and module-style call (src/sonar/app.py:30-31, dashboard.py:15,18, debts/model.py's own `from sonar import amortization`), plus docstrings/comments; no alias that reintroduces an old name. `git mv` tests into tests/debts/: test_debts.py → test_model.py, test_debts_status.py → test_model_status.py, test_debts_last_payment.py → test_model_last_payment.py, test_amortization.py (same), test_debt_store.py → test_store.py, test_debt_overview.py → test_store_overview.py, test_debt_remaining.py → test_store_remaining.py; add `__init__.py`. Page tests (test_debts_page*.py, test_debt_links_page.py, test_debts_refresh.py) stay for N08; only their imports change.
Spec: SPEC §7, §13 (loans); owner request
Read: src/sonar/debt_store.py:1-30, src/sonar/debts.py:1-20
Write: src/sonar/debts/**, src/sonar/{debts,amortization,debt_store}.py, import sites in src/sonar/{app,dashboard}.py, tests/debts/**, import sites in tests/ (incl. tests/test_forecast.py, tests/test_dashboard.py, tests/test_debts_page.py:13)
Test first: move the test files and point their imports at `sonar.debts.*`; they fail with ModuleNotFoundError until the modules move.
Done when:
- C1 src/sonar/debts/ holds `__init__.py`, `model.py`, `amortization.py`, `store.py`; src/sonar/amortization.py and debt_store.py are gone
- C2 `git status --short` shows the three modules and seven test files as renames (`R`)
- C3 `rg -n --pcre2 'sonar\.(amortization|debt_store)\b|from sonar\.debts import (?!model\b|amortization\b|store\b)|from sonar import .*\b(debts|amortization|debt_store)\b' src tests` prints nothing
- C4 `git diff -M HEAD -- tests | rg '^-\s*def test_'` prints nothing
- C5 the verify command exits 0
Findings:
- none

### N07 cashflow package
Do: Create the `cashflow` package with `git mv`: payday.py, balance.py, forecast.py, monthly.py, lights_on.py → cashflow/ (same names), settings_store.py → cashflow/store.py, dashboard.py → cashflow/service.py. `__init__.py` holds a one-line docstring only. Update every import site and module-style call (src/sonar/app.py:20,28,36,58, cashflow/service.py's own `from sonar import debts, forecast, lights_on, payday, spending_groups`-style imports as already rewritten by N04-N06), plus docstrings/comments; no alias that reintroduces an old name. `git mv` tests into tests/cashflow/: test_payday.py, test_balance.py, test_forecast.py, test_monthly.py, test_lights_on.py (same names), test_settings_store.py → test_store.py, test_dashboard.py → test_service.py; add `__init__.py`. Page tests stay for N08; only their imports change.
Spec: SPEC §8, §9, §13 (forecast, lights on); owner request
Read: src/sonar/dashboard.py:1-30, src/sonar/lights_on.py:20-30, src/sonar/monthly.py:20-30
Write: src/sonar/cashflow/**, src/sonar/{payday,balance,forecast,monthly,lights_on,settings_store,dashboard}.py, import sites in src/sonar/app.py, tests/cashflow/**, import sites in tests/ (incl. tests/test_real_sample.py, tests/test_monthly_page.py, tests/test_lights_on_page.py, tests/test_settings_page*.py)
Test first: move the test files and point their imports at `sonar.cashflow.*`; they fail with ModuleNotFoundError until the modules move.
Done when:
- C1 src/sonar/cashflow/ holds `__init__.py`, `payday.py`, `balance.py`, `forecast.py`, `monthly.py`, `lights_on.py`, `store.py`, `service.py`; the seven old top-level modules are gone
- C2 `git status --short` shows the seven modules and seven test files as renames (`R`)
- C3 `rg -n 'sonar\.(payday|balance|forecast|monthly|lights_on|settings_store|dashboard)\b|from sonar import .*\b(payday|balance|forecast|monthly|lights_on|settings_store|dashboard)\b' src tests` prints nothing
- C4 `uv run pytest tests/test_architecture.py --runxfail -q`: rule 1 reports only `app.py`; rule 4 reports only `api.py`, `app.py`, `charts.py`, `display.py`
- C5 `git diff -M HEAD -- tests | rg '^-\s*def test_'` prints nothing
- C6 the verify command exits 0
Findings:
- none

### N08 web package, templates and static
Do: Create the `web` package with `git mv`: app.py, api.py, display.py, charts.py → src/sonar/web/ (same names), src/sonar/templates/ → src/sonar/web/templates/, src/sonar/static/ → src/sonar/web/static/. `web/__init__.py` holds a one-line docstring only. `TEMPLATES_DIR`/`STATIC_DIR` (app.py:83-84, `Path(__file__).parent / ...`) keep working unchanged. Update imports: src/sonar/__main__.py → `from sonar.web.app import create_app` (allowed: the top-level `__main__.py` is rule 3's only exemption; `import-categories` keeps using `sonar.db.MIGRATIONS_DIR`, so only `main()` touches `sonar.web`); app.py's `sonar.api`/`sonar.display`/`sonar.charts`; charts.py:13. `git mv` into tests/web/ (same names): test_app, test_display, test_charts, test_components, test_shell, test_static, test_templates_hygiene, test_not_found, test_api_categories, test_api_rules, and every page test (`tests/test_*_page*.py`, `tests/test_*_refresh.py`, test_uncategorized_page, test_import_page, test_debt_links_page); add tests/web/__init__.py; update `sonar.app` imports to `sonar.web.app`, fixture paths to `Path(__file__).parent.parent / "fixtures"`, and the templates dir in test_templates_hygiene (tests/test_templates_hygiene.py:37,69,82) to src/sonar/web/templates. The tailwind `@source "../../templates"` (src/sonar/static/src/app.css:2) stays valid because both dirs move together. Rebuild CSS with `TAILWINDCSS_VERSION=v4.3.3 uv run tailwindcss -i src/sonar/web/static/src/app.css -o src/sonar/web/static/sonar.css --minify`. Remove the xfail markers from the rule 1, 2 and 4 real-tree tests in tests/test_architecture.py.
Spec: SPEC §12 (Tooling, UI acceptance); owner request
Read: src/sonar/app.py:1-90, tests/test_templates_hygiene.py:30-40, tests/test_architecture.py
Write: src/sonar/web/**, src/sonar/{app,api,display,charts}.py, src/sonar/templates/**, src/sonar/static/**, src/sonar/__main__.py, tests/web/**, the moved test files, tests/test_architecture.py
Test first: remove the three xfail markers first; rules 1, 2 and 4 fail naming app.py, api.py, charts.py, display.py until the moves are done.
Done when:
- C1 src/sonar/ top level holds only `__init__.py`, `__main__.py`, `db.py`, `money.py`, `transactions.py`, `migrations/` and the packages `importing`, `categorization`, `recurring`, `debts`, `cashflow`, `web`
- C2 `git status --short` shows the modules, every template, static file and moved test as renames (`R`); `git diff -M HEAD -- src/sonar/web/templates src/sonar/web/static` shows no content change
- C3 after the rebuild command, `git diff -M --stat HEAD -- src/sonar/web/static/sonar.css` shows a pure rename (no content change)
- C4 `rg -n 'sonar\.(app|api|display|charts)\b' src tests` prints nothing; `rg -ln 'sonar\.web|from sonar import web' src/sonar --glob '!web/**'` lists only src/sonar/__main__.py
- C5 tests/test_architecture.py: rules 1-4 have no xfail marker and pass; rule 5 keeps its marker
- C6 `git diff -M HEAD -- tests | rg '^-\s*def test_'` prints nothing
- C7 the verify command exits 0
Findings:
- none

### N09 page routers: dashboard, monthly, lights_on, uncategorized, import_
Do: Add src/sonar/web/pages/ (`__init__.py` with a one-line docstring) with modules dashboard.py, monthly.py, lights_on.py, uncategorized.py, import_.py, each exposing `build_router(db_path: Path, today: Callable[[], date], templates: Jinja2Templates) -> APIRouter` built like `build_api_router` (src/sonar/web/api.py, `def build_api_router`). `templates` is passed in by `create_app` because importing it from web/app.py would be circular. Move the route functions and their private helpers out of `create_app` in src/sonar/web/app.py, bodies unchanged except `@app.` → `@router.` (plan-time lines in the old app.py: `/` 433, `/monthly` 443, `/lights-on` 489 with `_cents`/`_lights_on_table_rows`/`_lights_on_chart_series` 174-219, `/uncategorized` 526, `/reapply` 543, `/uncategorized/badge` 557 with `_nav_badge` 102, `/import` GET/POST 566-590 with `_import_one` 1124). `create_app` includes the api router first, then these five routers in this order, in place of the moved routes (remaining routes keep their relative order). Drop imports app.py no longer uses.
Spec: SPEC §12 (pages); owner request
Read: src/sonar/web/app.py, src/sonar/web/api.py (build_api_router), tests/test_architecture.py (rule 5)
Write: src/sonar/web/app.py, src/sonar/web/pages/**
Test first: `uv run pytest tests/test_architecture.py --runxfail -k <rule 5 test> -q` lists `/`, `/monthly`, `/lights-on`, `/uncategorized`, `/reapply`, `/uncategorized/badge`, `/import`; afterwards none of these appear.
Done when:
- C1 the five modules exist, each defining `build_router` with the signature above, and together registering exactly the seven paths above with their methods
- C2 `rg -n '_nav_badge|_import_one|_lights_on_table_rows|_lights_on_chart_series|def _cents' src/sonar/web/app.py` prints nothing; each helper is defined once, in the page module that uses it
- C3 `git diff -M HEAD` shows the moved route bodies unchanged apart from the decorator object and indentation (verifier compares by reading)
- C4 no test file changes; `git diff HEAD --stat -- tests` is empty
- C5 the verify command exits 0
Findings:
- none

### N10 page routers: recurring, debts, settings, categories; forms.py
Do: Add src/sonar/web/forms.py with the form helpers from src/sonar/web/app.py, made public: `row_error` (from `_row_error`, old app.py:107), `field` (`_field` + `_FIELD_HINTS`, 116-138), `friendly` (`_friendly` + `_DOMAIN_ERROR_HINTS`, 139-164); pages use `from sonar.web import forms` and call `forms.field(...)`. Add pages recurring.py, debts.py, settings.py, categories.py with the same `build_router(db_path, today, templates)` as N09, moving routes and their helpers (plan-time lines: recurring 591-731 with `_render_recurring_page` 299 and `_validate_schedule` 1112; debts 734-845 with `_render_debts_page` 337; settings 846-913 with `_render_settings_page` 365; categories and `/categories/rules*` 914-1111 with `_render_categories_page` 382 and `_rule_form_fields` 975). After this, web/app.py holds only imports, `TEMPLATES_DIR`, `STATIC_DIR`, `templates` with its filters and globals (`_format_cents`, `_format_percent`, `_group_label` stay; tests import `_format_cents` and `templates` from `sonar.web.app`), and `create_app` (lifespan, static mount, api router, the nine page routers in the original route order, exception handlers). Remove the rule 5 xfail marker in tests/test_architecture.py.
Spec: SPEC §12 (Friendly errors); owner request
Read: src/sonar/web/app.py, src/sonar/web/pages/dashboard.py, tests/test_architecture.py
Write: src/sonar/web/app.py, src/sonar/web/forms.py, src/sonar/web/pages/{recurring,debts,settings,categories}.py, tests/test_architecture.py
Test first: remove the rule 5 xfail marker first; it fails listing the remaining recurring, debts, settings and categories paths until they move.
Done when:
- C1 `rg -n '@app\.' src/sonar/web/app.py` matches only `@app.exception_handler`; rule 5 passes with no xfail marker; `rg -n xfail tests/test_architecture.py` prints nothing
- C2 web/app.py defines no functions other than `create_app`, its lifespan and exception handlers, and the three filter functions; `rg -n '_row_error|_field\(|_friendly|_render_\w+_page|_rule_form_fields|_validate_schedule' src/sonar/web/app.py` prints nothing
- C3 src/sonar/web/forms.py defines `row_error`, `field`, `friendly` and the two hint tables; no page module defines its own copy; web/forms.py imports nothing from web/app.py or web/pages/
- C4 `create_app` includes routers in this order: api, dashboard, monthly, lights_on, uncategorized, import_, recurring, debts, settings, categories
- C5 moved route bodies are unchanged apart from the decorator object, indentation and the `forms.` prefix (verifier compares by reading `git diff -M HEAD`)
- C6 the only test file changed is tests/test_architecture.py (marker removed)
- C7 the verify command exits 0
Findings:
- none

### N11 docs: CLAUDE.md, planner.md, SPEC paths
Do: Update docs to the new layout, using the owner's wording verbatim. CLAUDE.md: the Setup build command (CLAUDE.md:12) uses `src/sonar/web/static/src/app.css` and `src/sonar/web/static/sonar.css`; replace the Layout bullets CLAUDE.md:22-26 with, in this order: "`src/sonar/<feature>/`: one package per feature (`importing`, `categorization`, `recurring`, `debts`, `cashflow`). Pure logic has a domain name (`detect.py`, `forecast.py`); `store.py` is the only DB access; `service.py` coordinates several stores." / "`src/sonar/web/`: `app.py` wires only; `pages/` has one router per page; `api.py`; `templates/` (`components/` holds the macros); `static/`" / "`src/sonar/importing/importers/`: one module per bank format (NAME, detect, parse, optional parse_balance), registered in IMPORTERS; a new source = one importer module + fixture tests" / "`src/sonar/`: top level holds only `__main__`, `db`, `money`, `transactions`, `migrations/`" / "`tests/`: follows `src/sonar/`'s layout (`tests/<feature>/`, `tests/web/`); `tests/html.py` holds the page-test helpers"; add after CLAUDE.md:37 the rule "- **Structure.** New code goes in an existing feature package; a new package needs a SPEC feature behind it. One concept has one name: its pure part and its store sit side by side, never as `x` / `x_ing` / `x_store` at the top level. A page's routes go in `web/pages/<page>.py`, never in `app.py`. `tests/test_architecture.py` enforces the import rules."; change `uncategorized_export.py:21` (CLAUDE.md:101) to `categorization/export.py:21`. .claude/agents/planner.md: add after the `Nodes:` line (planner.md:13) "A brief that creates a module names its package; a brief that adds a top-level module or a new package cites the SPEC section behind it." SPEC.md: `src/sonar/static/` → `src/sonar/web/static/` at SPEC.md:26, 184, 219; at SPEC.md:180 the module list reads `cashflow/forecast.py`, `cashflow/service.py`, `debts/model.py`, `recurring/store.py`, `variable_forecast.py`. pyproject.toml needs no change (entry point `sonar.__main__:main` unchanged; hatchling ships package data); leave it.
Spec: owner request; SPEC §12 (Tooling)
Read: CLAUDE.md:8-40,95-105, .claude/agents/planner.md, SPEC.md:24-28,178-186,216-220
Write: CLAUDE.md, .claude/agents/planner.md, SPEC.md
Test first: none (docs only); C1-C6 are the checks.
Done when:
- C1 CLAUDE.md Layout holds the five owner bullets verbatim in the given order, followed by the unchanged `data/`, `samples/`, `.plan/`, `.claude/` bullets; the old `src/sonar/`, `migrations/`, `templates/`, `importers/`, `tests/` bullets are gone
- C2 the Structure rule sits directly after the "Functional core, thin shell" rule, verbatim
- C3 the CLAUDE.md Setup build command paths exist on disk, and `sed -n 21p src/sonar/categorization/export.py` starts with `HEADER =` (the cited line is right)
- C4 `wc -l .claude/agents/planner.md` ≤ 25 and it contains the new sentence
- C5 `rg -n 'src/sonar/(static|templates|importers)|uncategorized_export|taxonomy_store|settings_store|debt_store|spending_groups' CLAUDE.md SPEC.md .claude pyproject.toml` prints nothing
- C6 no file outside CLAUDE.md, SPEC.md and .claude/agents/planner.md changes
Findings:
- none

### N12 visual check
Do: gate: the orchestrator starts the app on a temp DB, imports the real sample, sets salary day and balance, then opens Dashboard, Monthly, Keep the lights on, Uncategorized (incl. Re-apply rules and the nav badge), Import, Recurring, Debts, Settings, Categories and an unknown URL (404) at desktop and 375px, light and dark (read_page first, scaled screenshots only where layout matters). Submit one invalid form (Settings salary day `0`) to see the inline error.
Done when:
- C1 every listed page renders styled (sonar.css and htmx load from /static) with the same content as before the plan, with no 500 and no unstyled page
- C2 the invalid Settings form shows the inline `#form-error` alert with the entered value kept; the unknown URL shows the styled `error.html`
Findings:
- none

### N13 plan acceptance
Do: check the whole plan against its goal.
Done when:
- C1 the verify command exits 0
- C2 no test lost: `uv run pytest --collect-only -q | tail -1` at HEAD equals the count at 132cabf, the last commit before this plan (collect it in a temporary worktree under the scratchpad: `git worktree add <dir> 132cabf`, run `uv run pytest --collect-only -q | tail -1` there, then `git worktree remove <dir>`) plus the count collected from tests/test_architecture.py
- C3 SPEC §11 still holds (the areas touched are all of src/sonar; the suite plus `uv run python -c "import sonar.__main__"` and a `create_app` smoke run on a temp DB cover it)
- C4 SPEC §12 UI acceptance: rebuilding with the CLAUDE.md Setup command leaves src/sonar/web/static/sonar.css unchanged (`git diff --exit-code`); `git diff -M 132cabf --stat -- src/sonar/web/templates src/sonar/web/static src/sonar/migrations` shows renames only
- C5 tests/test_architecture.py passes with no xfail marker, and rule 3's only exemption is the top-level `__main__.py`; src/sonar top level holds only `__init__`, `__main__`, `db`, `money`, `transactions`, `migrations/` and the six packages; tests/ holds `__init__.py`, `html.py`, `seed.py`, `fixtures/`, top-level tests for those top-level modules plus test_architecture, test_html_helper and test_real_sample, and the subpackages importing, categorization, recurring, debts, cashflow, web, migrations, each with `__init__.py`
- C6 history follows the moves: `git log --follow --oneline -- src/sonar/recurring/detect.py` and `-- src/sonar/web/app.py` list commits older than this plan
- C7 `rg -n 'sonar\.(app|api|display|charts|dedup|importers|categorize|categorizing|taxonomy_store|taxonomy_service|uncategorized_export|spending_groups|schedule|recurrence|debt_store|amortization|payday|balance|forecast|monthly|lights_on|settings_store|dashboard)\b' src tests CLAUDE.md SPEC.md .claude` prints nothing
Findings:
- try 1: C2 .plan/2026-09-30-feature-package-structure.md:221 baseline stale: HEAD collects 833; e4d88fb 806 + test_architecture 18 = 824; the 9-test gap is the four forecast-from-balance-date commits after e4d88fb; at 132cabf (real pre-plan base) 815 + 18 = 833; no test lost in the move
