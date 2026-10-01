"""Commit a DONE node's work."""

import argparse
import os
import shutil
import subprocess
from pathlib import Path

from planzilla.commands._common import (
    LockTimeout,
    ResolveError,
    fail,
    plan_lock,
    resolve_plan,
    write_atomic,
)
from planzilla.config import load_config
from planzilla.plan import Plan, PlanError, load_brief, load_plan


class CommandError(Exception):
    """A failure that ends the command with `error: <message>` and an exit code."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


# --- pure helpers (FORMAT §10) ---------------------------------------------


def commit_message(slug: str, node_id: str, title: str, trailer: str) -> str:
    """Subject `<slug> <id>: <title>`, then a blank line and the trailer lines when set."""
    message = f"{slug} {node_id}: {title}\n"
    if trailer:
        message += f"\n{trailer}\n"
    return message


def write_specs(write: list[str]) -> list[str]:
    """Git glob pathspecs for Write items; a trailing `/` means `/**` (FORMAT §6)."""
    return [":(glob)" + (item + "**" if item.endswith("/") else item) for item in write]


def plan_files(files: list[str], plan_rel: str, node_id: str, is_dir: bool) -> list[str]:
    """The plan's files to stage: all of an L plan except `log/` and `runs/`, plus this node's."""
    if not is_dir:
        return [path for path in files if path == plan_rel]
    keep = []
    for path in files:
        rel = path.removeprefix(plan_rel + "/")
        if rel.startswith("log/"):
            wanted = rel == f"log/{node_id}.md"
        elif rel.startswith("runs/"):
            wanted = rel.startswith(f"runs/{node_id}/")
        else:
            wanted = True
        if wanted:
            keep.append(path)
    return keep


def strip_log_section(text: str) -> str:
    """An S/M plan text without its trailing `## Log` section."""
    lines = text.split("\n")
    if "## Log" not in lines:
        return text
    kept = lines[: lines.index("## Log")]
    while kept and not kept[-1].strip():
        kept.pop()
    return "\n".join(kept) + "\n"


# --- git ---------------------------------------------------------------------


def _first_line(*texts: str) -> str:
    for text in texts:
        for line in text.splitlines():
            if line.strip():
                return line.strip()
    return "unknown error"


def _git(
    root: Path,
    *args: str,
    stdin: str | None = None,
    literal: bool = False,
    check: bool = True,
) -> subprocess.CompletedProcess:
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0")
    if literal:
        env["GIT_LITERAL_PATHSPECS"] = "1"
    try:
        result = subprocess.run(
            ["git", *args], cwd=root, input=stdin, capture_output=True, text=True, env=env
        )
    except OSError as error:
        raise CommandError(3, f"git failed: {error}") from None
    if check and result.returncode != 0:
        raise CommandError(3, f"git {args[0]} failed: {_first_line(result.stderr, result.stdout)}")
    return result


def _listed(root: Path, specs: list[str]) -> list[str]:
    """Tracked and untracked (not ignored) files matching the pathspecs; deleted ones included."""
    if not specs:
        return []
    out = _git(root, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *specs)
    return [path for path in out.stdout.split("\0") if path]


def _remove(root: Path, rels: list[str]) -> None:
    """Remove paths from the index and the working tree."""
    _git(root, "rm", "-r", "-q", "-f", "--ignore-unmatch", "--", *rels, literal=True)
    for rel in rels:
        path = root / rel
        if path.is_dir():
            shutil.rmtree(path)
        elif path.exists():
            path.unlink()


# --- command -----------------------------------------------------------------


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("plan", help="plan path or slug fragment")
    parser.add_argument("node", help="node id, e.g. N03")


def run(args: argparse.Namespace) -> int:
    try:
        return _run(args.plan, args.node)
    except CommandError as error:
        return fail(str(error), error.code)
    except (PlanError, ResolveError) as error:
        return fail(str(error), 2)
    except LockTimeout as error:
        return fail(str(error), 3)


def _run(ref: str, node_id: str) -> int:
    plan_path = resolve_plan(ref, Path.cwd())
    with plan_lock(plan_path):
        return _commit(plan_path, node_id)


def _commit(plan_path: Path, node_id: str) -> int:
    plan = load_plan(plan_path)
    node = plan.node(node_id)
    if plan.header.commit == "none":
        print(f"{node_id} commit skipped: commit none")
        return 0
    if node.status != "DONE":
        raise CommandError(2, f"node {node_id} is {node.status}, not DONE")
    config = load_config(plan.root)
    root = plan.root
    plan_rel = plan.path.relative_to(root).as_posix()

    brief = load_brief(plan, node_id)
    specs = write_specs(brief.write or [] if brief else [])
    staged = set(_listed(root, specs))
    staged.update(plan_files(_listed(root, [plan_rel]), plan_rel, node_id, plan.is_dir))
    if staged:
        names = "\0".join(sorted(staged))
        _git(
            root,
            "add",
            "-A",
            "--pathspec-from-file=-",
            "--pathspec-file-nul",
            stdin=names,
            literal=True,
        )

    message = commit_message(plan.slug, node_id, node.title, config.commit_trailer)
    finishing = plan.header.status == "DONE"
    side_branch = None
    if finishing:
        if config.retention == "branch-only":
            side_branch = f"plan/{plan.slug}"
            _side_commit(root, side_branch, message)
        _apply_retention(plan, config.retention, root, plan_rel)
    _git(root, "commit", "-q", "-F", "-", stdin=message)
    sha = _git(root, "rev-parse", "HEAD").stdout.strip()[:7]

    line = f"{node_id} committed {sha}"
    if finishing:
        line += f" · plan DONE · retention {config.retention}"
    code = 0
    if (plan.header.push or config.push) == "per-node":
        failure = _push(root, side_branch)
        line += " · pushed" if failure is None else f" · push failed: {failure}"
        code = 0 if failure is None else 3
    print(line)
    return code


def _side_commit(root: Path, branch: str, message: str) -> None:
    """Commit the staged tree onto `branch` (parent = HEAD) without moving HEAD."""
    tree = _git(root, "write-tree").stdout.strip()
    has_head = _git(root, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0
    parent = ["-p", "HEAD"] if has_head else []
    sha = _git(root, "commit-tree", tree, *parent, "-F", "-", stdin=message).stdout.strip()
    _git(root, "update-ref", f"refs/heads/{branch}", sha)


def _apply_retention(plan: Plan, retention: str, root: Path, plan_rel: str) -> None:
    if retention == "prune-logs":
        if plan.is_dir:
            _remove(root, [f"{plan_rel}/log", f"{plan_rel}/runs"])
        else:
            stripped = strip_log_section(plan.text)
            if stripped != plan.text:
                write_atomic(plan.graph_file, stripped)
                _git(root, "add", "-A", "--", plan_rel, literal=True)
    elif retention in ("delete", "branch-only"):
        _remove(root, [plan_rel])


def _push(root: Path, side_branch: str | None) -> str | None:
    """Push HEAD (and the side branch); None on success, else the first stderr line."""
    steps = [("push", "-u", "origin", "HEAD")]
    if side_branch:
        steps.append(("push", "origin", side_branch))
    for step in steps:
        result = _git(root, *step, check=False)
        if result.returncode != 0:
            return _first_line(result.stderr)
    return None
