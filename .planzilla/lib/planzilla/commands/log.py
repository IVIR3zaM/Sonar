"""Append a log entry for a node.

Also holds the helpers `brief` and `check` share: command errors and log reading (FORMAT §7).
Plan resolution, locking and writing live in `_common`.
"""

import argparse
import datetime
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from planzilla.commands._common import (
    GitError,
    LockTimeout,
    ResolveError,
    append_log,
    fail,
    plan_lock,
    resolve_plan,
)
from planzilla.plan import Plan, PlanError, load_plan, node_paths

KINDS = ("exec", "verify", "plan", "human", "note")

_FAIL_RE = re.compile(r"(check|verify): FAIL( |$)")


class CliError(Exception):
    """A command failure: printed as `error: <message>`, exit `code` (FORMAT §9)."""

    def __init__(self, message: str, code: int = 2) -> None:
        super().__init__(message)
        self.code = code


def guarded(func: Callable[[argparse.Namespace], int], args: argparse.Namespace) -> int:
    """Run a command body; turn its errors into the one-line `error:` form."""
    try:
        return func(args)
    except CliError as error:
        return fail(str(error), error.code)
    except (PlanError, ResolveError) as error:
        return fail(str(error), 2)
    except (LockTimeout, GitError) as error:
        return fail(str(error), 3)


def today() -> str:
    return datetime.date.today().isoformat()


# --- log reading (pure) ------------------------------------------------------


@dataclass
class Entry:
    """One log entry of a node: its key (`try 1`, `brief`, `replan 1`) and the lines under it."""

    key: str
    lines: list[str]


def heading_key(heading: str) -> str:
    """The attempt key of a heading text: everything before ` · <date>`."""
    return heading.split(" · ")[0].strip()


def _log_start(lines: list[str]) -> int | None:
    return lines.index("## Log") if "## Log" in lines else None


def parse_entries(text: str, is_dir: bool, node_id: str) -> list[Entry]:
    """The node's entries, in order. L: the log file text; S/M: the plan file text."""
    lines = text.split("\n")
    if not is_dir:
        start = _log_start(lines)
        lines = [] if start is None else lines[start + 1 :]
    prefix = "## " if is_dir else "### "
    entries: list[Entry] = []
    current: Entry | None = None
    for line in lines:
        if line.startswith(prefix):
            key = heading_key(line[len(prefix) :])
            if not is_dir:
                owner, _, key = key.partition(" ")
                if owner != node_id:
                    current = None
                    continue
            current = Entry(key, [])
            entries.append(current)
        elif current is not None:
            current.lines.append(line)
    return entries


def last_findings(entries: list[Entry]) -> list[str]:
    """The last `check: FAIL` or `verify: FAIL` line with its bullets (FORMAT §7)."""
    for entry in reversed(entries):
        for index in range(len(entry.lines) - 1, -1, -1):
            if not _FAIL_RE.match(entry.lines[index]):
                continue
            found = [entry.lines[index]]
            for line in entry.lines[index + 1 :]:
                if line.startswith("- "):
                    found.append(line)
                elif line.strip():
                    break
            return found
    return []


def has_rerun_marker(entries: list[Entry], tries: int) -> bool:
    """A `resume:` line after the last heading whose key is `try <tries>` (FORMAT §7)."""
    for index in range(len(entries) - 1, -1, -1):
        if entries[index].key == f"try {tries}":
            return any(
                line.startswith("resume:") for entry in entries[index:] for line in entry.lines
            )
    return False


def read_log(plan: Plan, node_id: str) -> str:
    """The text `parse_entries` reads: the node's log file (L, may be missing) or the plan file."""
    path = node_paths(plan, node_id).log
    return path.read_bytes().decode("utf-8") if path.is_file() else ""


# --- command -----------------------------------------------------------------


def _one_line(text: str) -> str:
    return " ".join(text.split())


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("plan", help="plan path or slug fragment")
    parser.add_argument("node", help="node id")
    parser.add_argument("kind", help=f"entry kind: {', '.join(KINDS)}")
    parser.add_argument("text", help="text after the kind")
    parser.add_argument(
        "-b", "--bullet", dest="bullets", action="append", default=[], help="a bullet line"
    )


def _run(args: argparse.Namespace) -> int:
    if args.kind not in KINDS:
        raise CliError(f"unknown kind {args.kind!r}; expected one of {', '.join(KINDS)}")
    path = resolve_plan(args.plan, Path.cwd())
    with plan_lock(path):
        plan = load_plan(path)
        bullets = [_one_line(bullet) for bullet in args.bullets]
        append_log(plan, args.node, args.kind, _one_line(args.text), bullets, today())
    return 0


def run(args: argparse.Namespace) -> int:
    return guarded(_run, args)
