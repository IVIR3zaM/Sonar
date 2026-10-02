# Planzilla config (FORMAT §8). A missing key takes its default; a plan's header wins over this file.

# Engineering rules (TDD, structure, visual check, SPEC §11/§12 check node) live in AGENTS.md, not here.

verify: uv run pytest -q && uv run ruff check . && uv run ruff format --check .
verify_fast: uv run pytest -q -x && uv run ruff check .
commit: per-node
push: none
retention: keep
visual_recipe: uv run python -c "import uvicorn; from pathlib import Path; from sonar.web.app import create_app; uvicorn.run(create_app(Path('$TMPDIR/sonar-visual.db')), host='127.0.0.1', port=8000)" in the background (temp DB, never data/sonar.db), import the newest file in samples/ on /import, set salary day and balance on /settings, then open http://127.0.0.1:8000 and check every changed page at desktop and 375px, light and dark
models: planner=opus, exec=sonnet, verify=sonnet
preauthorized: rebuild and commit src/sonar/web/static/sonar.css after template or CSS changes; add a new migrations/NNNN_*.sql; start the app on a temp DB for smoke runs and visual checks
always_review: no
