"""IO helpers shared by the plan commands: plan reference, lock, atomic writes, log, git check.

Not a command (never listed in `cli.COMMANDS`). Callers hold `plan_lock` around writes; the helpers
here never lock. Pure text rendering lives in `planzilla.plan`.
"""

import os
import subprocess
import sys
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from planzilla.plan import (
    PLAN_NAME,
    Plan,
    append_entry,
    attempt_key,
    find_plans,
    parse_plan,
    render_plan,
)


class ResolveError(Exception):
    """A plan reference that matches no plan or several (exit 2)."""


class LockTimeout(Exception):
    """The plan lock could not be taken in time (exit 3)."""


class GitError(Exception):
    """A git call failed (exit 3)."""


def fail(message: str, code: int) -> int:
    """Print `error: <message>` to stderr and return the exit code."""
    print(f"error: {message}", file=sys.stderr)
    return code


def _is_plan_path(path: Path) -> bool:
    if path.parent.name != ".plan":
        return False
    if path.is_dir():
        return PLAN_NAME.fullmatch(path.name) is not None
    return path.is_file() and path.suffix == ".md" and PLAN_NAME.fullmatch(path.stem) is not None


def resolve_plan(ref: str, cwd: Path) -> Path:
    """Resolve a plan reference (FORMAT §9): a plan path or a unique name fragment in `.plan/`."""
    path = Path(ref) if Path(ref).is_absolute() else cwd / ref
    if ref and _is_plan_path(path):
        return path
    names = {p: (p.name if p.is_dir() else p.stem) for p in find_plans(cwd)}
    found = [p for p, name in names.items() if ref and ref in name]
    if not found:
        raise ResolveError(f"no plan matches {ref!r}")
    if len(found) > 1:
        raise ResolveError(f"{ref!r} matches several plans: {', '.join(names[p] for p in found)}")
    return found[0]


@contextmanager
def plan_lock(
    plan_path: Path, timeout: float = 10.0, stale: float = 60.0, poll: float = 0.05
) -> Iterator[None]:
    """Hold the lock directory `<plan path>.lock` (FORMAT §9); always removed on exit."""
    lock = plan_path.with_name(plan_path.name + ".lock")
    deadline = time.monotonic() + timeout
    while True:
        try:
            os.mkdir(lock)
            break
        except FileExistsError:
            pass
        try:
            if time.time() - lock.stat().st_mtime > stale:
                lock.rmdir()
                continue
        except FileNotFoundError:
            continue
        if time.monotonic() >= deadline:
            raise LockTimeout(f"timed out waiting for lock {lock}")
        time.sleep(poll)
    try:
        yield
    finally:
        try:
            lock.rmdir()
        except FileNotFoundError:
            pass


def write_atomic(path: Path, text: str) -> None:
    """Write `text` as UTF-8 to a temp file next to `path`, then `os.replace` it."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)


def write_plan(plan: Plan, status: str, today: str) -> Plan:
    """Write Graph changes plus header `status:`/`updated:`; return the reloaded plan."""
    text = render_plan(plan, status, today)
    write_atomic(plan.graph_file, text)
    return parse_plan(text, plan.path, plan.graph_file)


def append_log(
    plan: Plan, node_id: str, kind: str, text: str, bullets: list[str], today: str
) -> None:
    """Append one entry to the node's log (FORMAT §7); earlier bytes stay unchanged."""
    key = attempt_key(plan.node(node_id))
    if plan.is_dir:
        file = plan.path / "log" / f"{node_id}.md"
        old = file.read_bytes().decode("utf-8") if file.is_file() else f"# {node_id} log\n"
        heading = f"## {key} · {today}"
        file.parent.mkdir(parents=True, exist_ok=True)
    else:
        file = plan.graph_file
        old = file.read_bytes().decode("utf-8")
        if not any(line == "## Log" for line in old.split("\n")):
            old = old.rstrip("\n") + "\n\n## Log\n"
        heading = f"### {node_id} {key} · {today}"
    write_atomic(file, append_entry(old, heading, kind, text, bullets))


def uncommitted(root: Path, paths: Sequence[str | Path]) -> bool:
    """True when `git status --porcelain` reports any change among `paths`; GitError on failure."""
    if not paths:
        return False
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "--", *map(str, paths)],
            cwd=root,
            capture_output=True,
            text=True,
        )
    except OSError as error:
        raise GitError(f"git failed: {error}") from error
    if result.returncode != 0:
        raise GitError(f"git status failed: {result.stderr.strip()}")
    return bool(result.stdout.strip())
