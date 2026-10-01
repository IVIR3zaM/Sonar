"""Print the status of a plan.

Also holds `load_report`, which `stats` shares: it reads the plan, its logs and `git log`.
Read-only: no lock, no write (FORMAT §12).
"""

import argparse
import subprocess
import time
from pathlib import Path

from planzilla.commands._common import ResolveError, fail, resolve_plan
from planzilla.commands.log import read_log
from planzilla.plan import PlanError, load_plan
from planzilla.report import Commit, Report, build_report, format_status, parse_git_log
from planzilla.state import StateError


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("plan", help="plan path or slug fragment")


def now() -> int:
    return int(time.time())


def git_commits(root: Path, plan_path: Path) -> list[Commit]:
    """`git log --format='%ct %s' -- <plan path>` in the repo root; no commits when git fails."""
    try:
        result = subprocess.run(
            ["git", "log", "--format=%ct %s", "--", str(plan_path.relative_to(root))],
            cwd=root,
            capture_output=True,
            text=True,
        )
    except (OSError, ValueError):
        return []
    return parse_git_log(result.stdout) if result.returncode == 0 else []


def load_report(ref: str, cwd: Path) -> Report:
    """Resolve `ref` and build the report from files and git log only."""
    plan = load_plan(resolve_plan(ref, cwd))
    logs = {node.id: read_log(plan, node.id) for node in plan.nodes}
    return build_report(plan, logs, git_commits(plan.root, plan.path), now())


def run(args: argparse.Namespace) -> int:
    try:
        report = load_report(args.plan, Path.cwd())
    except (ResolveError, PlanError, StateError) as error:
        return fail(str(error), 2)
    print(format_status(report))
    return 0
