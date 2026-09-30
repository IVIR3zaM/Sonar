"""Architecture rules: who may import what, and which modules live at the top level."""

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src" / "sonar"

TOP_LEVEL_MODULES = {"__init__", "__main__", "db", "money", "transactions"}
ROUTE_METHODS = {"get", "post", "put", "delete", "patch"}

in_progress = pytest.mark.xfail(strict=False, reason="feature-package moves in progress")


def python_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.py"))


def rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def imported_names(path: Path) -> set[str]:
    """Dotted names imported by a file: the module, and `module.name` per name."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def imported_roots(path: Path) -> set[str]:
    return {name.split(".")[0] for name in imported_names(path)}


def importers_of(root: Path, packages: set[str], allowed) -> list[str]:
    offenders = set()
    for path in python_files(root):
        if allowed(rel(path, root)):
            continue
        for package in imported_roots(path) & packages:
            offenders.add(f"{rel(path, root)}: {package}")
    return sorted(offenders)


def sqlite_offenders(root: Path) -> list[str]:
    def allowed(rel_path: str) -> bool:
        parts = rel_path.split("/")
        return (
            rel_path == "db.py"
            or parts[0] == "web"
            or (len(parts) == 2 and parts[1] in {"store.py", "service.py"})
        )

    return importers_of(root, {"sqlite3"}, allowed)


def web_framework_offenders(root: Path) -> list[str]:
    return importers_of(
        root,
        {"fastapi", "starlette", "jinja2"},
        lambda rel_path: rel_path.split("/")[0] == "web",
    )


def web_import_offenders(root: Path) -> list[str]:
    offenders = set()
    for path in python_files(root):
        rel_path = rel(path, root)
        # The entry point wires the app for uvicorn; no other __main__ is exempt.
        if rel_path.split("/")[0] == "web" or rel_path == "__main__.py":
            continue
        for name in imported_names(path):
            if name == "sonar.web" or name.startswith("sonar.web."):
                offenders.add(f"{rel_path}: {name}")
    return sorted(offenders)


def top_level_offenders(root: Path) -> list[str]:
    return sorted(
        f"{path.name}: top-level module not allowed"
        for path in root.glob("*.py")
        if path.stem not in TOP_LEVEL_MODULES
    )


def route_path(decorator: ast.expr) -> str | None:
    if not (
        isinstance(decorator, ast.Call)
        and isinstance(decorator.func, ast.Attribute)
        and decorator.func.attr in ROUTE_METHODS
    ):
        return None
    first = decorator.args[0] if decorator.args else None
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return first.value
    return "<dynamic>"


def app_route_offenders(root: Path) -> list[str]:
    app = root / "web" / "app.py"
    if not app.exists():
        return []
    offenders = set()
    for node in ast.walk(ast.parse(app.read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                if (path := route_path(decorator)) is not None:
                    offenders.add(f"web/app.py: {path}")
    return sorted(offenders)


def write(root: Path, rel_path: str, source: str) -> None:
    target = root / rel_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(source)


# Real tree


@in_progress
def test_only_storage_modules_import_sqlite3():
    offenders = sqlite_offenders(SRC)
    assert not offenders, "\n".join(offenders)


@in_progress
def test_only_web_imports_web_frameworks():
    offenders = web_framework_offenders(SRC)
    assert not offenders, "\n".join(offenders)


def test_only_web_imports_web():
    offenders = web_import_offenders(SRC)
    assert not offenders, "\n".join(offenders)


@in_progress
def test_top_level_modules_are_the_shared_few():
    offenders = top_level_offenders(SRC)
    assert not offenders, "\n".join(offenders)


@in_progress
def test_web_app_has_no_routes():
    offenders = app_route_offenders(SRC)
    assert not offenders, "\n".join(offenders)


# Synthetic sanity checks


def test_sqlite_rule_reports_a_route_module(tmp_path):
    write(tmp_path, "cashflow/forecast.py", "import sqlite3\n")
    assert sqlite_offenders(tmp_path) == ["cashflow/forecast.py: sqlite3"]


def test_sqlite_rule_reports_from_import(tmp_path):
    write(tmp_path, "app.py", "from sqlite3 import Connection\n")
    assert sqlite_offenders(tmp_path) == ["app.py: sqlite3"]


def test_sqlite_rule_allows_db_store_service_and_web(tmp_path):
    for rel_path in ("db.py", "cashflow/store.py", "debts/service.py", "web/app.py"):
        write(tmp_path, rel_path, "import sqlite3\n")
    assert sqlite_offenders(tmp_path) == []


def test_sqlite_rule_rejects_nested_store(tmp_path):
    write(tmp_path, "cashflow/deep/store.py", "import sqlite3\n")
    assert sqlite_offenders(tmp_path) == ["cashflow/deep/store.py: sqlite3"]


def test_framework_rule_reports_each_framework(tmp_path):
    write(tmp_path, "api.py", "import fastapi\n")
    write(tmp_path, "debts/view.py", "from starlette.responses import Response\n")
    write(tmp_path, "display.py", "import jinja2\n")
    assert web_framework_offenders(tmp_path) == [
        "api.py: fastapi",
        "debts/view.py: starlette",
        "display.py: jinja2",
    ]


def test_framework_rule_allows_web(tmp_path):
    write(tmp_path, "web/app.py", "import fastapi\nimport jinja2\n")
    write(tmp_path, "web/pages/debts.py", "from starlette.requests import Request\n")
    assert web_framework_offenders(tmp_path) == []


def test_web_rule_reports_imports_of_web(tmp_path):
    write(tmp_path, "cashflow/a.py", "import sonar.web.app\n")
    write(tmp_path, "cashflow/b.py", "from sonar.web import app\n")
    write(tmp_path, "cashflow/c.py", "from sonar import web\n")
    assert web_import_offenders(tmp_path) == [
        "cashflow/a.py: sonar.web.app",
        "cashflow/b.py: sonar.web",
        "cashflow/b.py: sonar.web.app",
        "cashflow/c.py: sonar.web",
    ]


def test_web_rule_allows_web_and_top_level_main(tmp_path):
    write(tmp_path, "web/pages/debts.py", "from sonar.web.app import create_app\n")
    write(tmp_path, "__main__.py", "from sonar.web.app import create_app\n")
    assert web_import_offenders(tmp_path) == []


def test_web_rule_does_not_exempt_subpackage_main(tmp_path):
    write(tmp_path, "cashflow/__main__.py", "import sonar.web.app\n")
    assert web_import_offenders(tmp_path) == ["cashflow/__main__.py: sonar.web.app"]


def test_top_level_rule_reports_stray_modules(tmp_path):
    write(tmp_path, "schedule.py", "")
    write(tmp_path, "app.py", "")
    assert top_level_offenders(tmp_path) == [
        "app.py: top-level module not allowed",
        "schedule.py: top-level module not allowed",
    ]


def test_top_level_rule_allows_shared_modules_and_packages(tmp_path):
    for name in TOP_LEVEL_MODULES:
        write(tmp_path, f"{name}.py", "")
    write(tmp_path, "cashflow/schedule.py", "")
    assert top_level_offenders(tmp_path) == []


def test_route_rule_reports_route_paths(tmp_path):
    write(
        tmp_path,
        "web/app.py",
        "@app.get('/x')\ndef x(): ...\n\n@router.post('/y/{id}')\nasync def y(): ...\n",
    )
    assert app_route_offenders(tmp_path) == ["web/app.py: /x", "web/app.py: /y/{id}"]


def test_route_rule_ignores_other_decorators_and_missing_app(tmp_path):
    assert app_route_offenders(tmp_path) == []
    write(tmp_path, "web/app.py", "@cache\ndef f(): ...\n")
    write(tmp_path, "web/pages/x.py", "@router.get('/z')\ndef z(): ...\n")
    assert app_route_offenders(tmp_path) == []
