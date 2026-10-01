"""Check a plan against the planner rules (FORMAT §9 `lint`, D12).

Read-only: no lock, no write. One `<file>:<line>: <rule>: <message>` line per problem, exit 1 when
there are any; when clean, `lint ok: <n> nodes, <w> waves`.
"""

import argparse
import dataclasses
from collections.abc import Sequence
from fnmatch import fnmatchcase
from functools import cache
from pathlib import Path

from planzilla.commands._common import ResolveError, fail, resolve_plan
from planzilla.plan import TAGS, Brief, Plan, PlanError, load_brief, load_plan
from planzilla.state import StateError, waves

MAX_BRIEF_LINES = 40


@dataclasses.dataclass(frozen=True)
class Problem:
    file: Path
    line: int
    rule: str
    message: str


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("plan", help="plan path or slug fragment")


# --- Write path overlap (FORMAT §6) --------------------------------------------


def _segments(item: str) -> tuple[str, ...]:
    return tuple((item + "**" if item.endswith("/") else item).split("/"))


def _compatible(a: str, b: str) -> bool:
    if a == b or ("*" in a and "*" in b):
        return True
    if "*" in a:
        return fnmatchcase(b, a)
    if "*" in b:
        return fnmatchcase(a, b)
    return False


@cache
def _overlap(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    if not a:
        return all(segment == "**" for segment in b)
    if not b:
        return all(segment == "**" for segment in a)
    if a[0] == "**":
        return _overlap(a[1:], b) or _overlap(a, b[1:])
    if b[0] == "**":
        return _overlap(a, b[1:]) or _overlap(a[1:], b)
    return _compatible(a[0], b[0]) and _overlap(a[1:], b[1:])


def items_overlap(a: str, b: str) -> bool:
    """True when some path could match both Write items."""
    return _overlap(_segments(a), _segments(b))


# --- rules ---------------------------------------------------------------------


def _brief_problems(brief: Brief) -> list[Problem]:
    problems = []
    size = len(brief.text.split("\n"))
    if size > MAX_BRIEF_LINES:
        message = f"brief {brief.id} has {size} lines (max {MAX_BRIEF_LINES})"
        problems.append(Problem(brief.file, brief.line, "length", message))
    for criterion in brief.criteria:
        if criterion.tag is None:
            message = f"criterion {criterion.id} has no tag"
            problems.append(Problem(brief.file, criterion.line, "tag", message))
        elif criterion.tag not in TAGS:
            message = f"criterion {criterion.id} has unknown tag [{criterion.tag}]"
            problems.append(Problem(brief.file, criterion.line, "tag", message))
        elif criterion.tag == "cmd" and criterion.command is None:
            message = f"criterion {criterion.id} [cmd] must start with a backticked command"
            problems.append(Problem(brief.file, criterion.line, "cmd", message))
    return problems


def _graph_problems(plan: Plan) -> tuple[list[Problem], dict[str, int] | None]:
    """Problems of the Graph (`deps`, `cycle`) and the waves, or None when it has a cycle."""
    problems = []
    ids = {node.id for node in plan.nodes}
    for node in plan.nodes:
        for dep in node.deps:
            if dep not in ids:
                message = f"{node.id} depends on {dep}, which is not a node"
                problems.append(Problem(plan.graph_file, node.line or 1, "deps", message))
    known = [
        dataclasses.replace(node, deps=[dep for dep in node.deps if dep in ids])
        for node in plan.nodes
    ]
    try:
        return problems, waves(known)
    except StateError as error:
        text = str(error).removeprefix("cycle ")
        members = set(text.split(" -> "))
        first = next(node for node in plan.nodes if node.id in members)
        message = f"Graph has a cycle: {text}"
        problems.append(Problem(plan.graph_file, first.line or 1, "cycle", message))
        return problems, None


def _overlap_problems(plan: Plan, briefs: dict[str, Brief], level: dict[str, int]) -> list[Problem]:
    problems = []
    nodes = [node for node in plan.nodes if briefs.get(node.id) and briefs[node.id].write]
    for position, second in enumerate(nodes):
        for first in nodes[:position]:
            if level[first.id] != level[second.id]:
                continue
            for item in briefs[second.id].write or []:
                for other in briefs[first.id].write or []:
                    if items_overlap(item, other):
                        brief = briefs[second.id]
                        message = (
                            f"{second.id} Write `{item}` overlaps {first.id} Write `{other}`"
                            f" (same wave {level[first.id]})"
                        )
                        line = brief.field_lines.get("Write", brief.line)
                        problems.append(Problem(brief.file, line, "overlap", message))
    return problems


def lint_plan(plan: Plan) -> tuple[list[Problem], int]:
    """All problems of a parsed plan, and its number of waves."""
    problems, level = _graph_problems(plan)
    briefs: dict[str, Brief] = {}
    for node in plan.nodes:
        try:
            brief = load_brief(plan, node.id)
        except PlanError as error:
            problems.append(Problem(error.file, error.line, "parse", error.message))
            continue
        if brief is not None:
            briefs[node.id] = brief
            problems += _brief_problems(brief)
    if level is not None:
        problems += _overlap_problems(plan, briefs, level)
    return problems, max(level.values(), default=0) if level else 0


def format_problem(problem: Problem, root: Path) -> str:
    try:
        file = problem.file.relative_to(root)
    except ValueError:
        file = problem.file
    return f"{file.as_posix()}:{problem.line}: {problem.rule}: {problem.message}"


def report_lines(problems: Sequence[Problem], root: Path) -> list[str]:
    ordered = sorted(problems, key=lambda p: (p.file.as_posix(), p.line))
    return [format_problem(problem, root) for problem in ordered]


# --- command -------------------------------------------------------------------


def run(args: argparse.Namespace) -> int:
    try:
        path = resolve_plan(args.plan, Path.cwd())
    except ResolveError as error:
        return fail(str(error), 2)
    root = path.parent.parent
    graph_file = path / "plan.md" if path.is_dir() else path
    if not graph_file.is_file():
        return fail(f"plan file not found: {graph_file}", 2)
    try:
        plan = load_plan(path)
    except PlanError as error:
        print(format_problem(Problem(error.file, error.line, "parse", error.message), root))
        return 1
    except (OSError, UnicodeDecodeError) as error:
        return fail(f"cannot read {graph_file}: {error}", 2)
    try:
        problems, wave_count = lint_plan(plan)
    except (OSError, UnicodeDecodeError) as error:
        return fail(f"cannot read plan files: {error}", 2)
    if problems:
        for line in report_lines(problems, root):
            print(line)
        return 1
    print(f"lint ok: {len(plan.nodes)} nodes, {wave_count} waves")
    return 0
