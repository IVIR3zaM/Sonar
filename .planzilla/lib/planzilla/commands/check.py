"""Run a node's [cmd] criteria."""

import argparse
import os
import signal
import subprocess
from dataclasses import dataclass
from pathlib import Path

from planzilla.commands import log
from planzilla.commands._common import append_log, plan_lock, resolve_plan, write_atomic
from planzilla.plan import Criterion, Node, attempt_key, load_brief, load_plan, node_paths

TIMEOUT = 900
LAST_LINE_MAX = 120


@dataclass
class Result:
    id: str
    command: str
    code: str
    output: str

    @property
    def passed(self) -> bool:
        return self.code == "0"


def run_command(criterion: Criterion, root: Path, timeout: float) -> Result:
    """Run the criterion's backticked command with `sh -c` from the repo root."""
    command = criterion.command or ""
    process = subprocess.Popen(
        ["sh", "-c", command],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
        code = str(process.returncode)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        output, _ = process.communicate()
        code = "timeout"
    return Result(criterion.id, command, code, output.decode("utf-8", errors="replace"))


def evidence_text(results: list[Result]) -> str:
    """FORMAT §7: per criterion `== C<k> <command>`, `exit <code>`, then the output."""
    parts = []
    for result in results:
        output = result.output
        if output and not output.endswith("\n"):
            output += "\n"
        parts.append(f"== {result.id} {result.command}\nexit {result.code}\n{output}")
    return "".join(parts)


def _last_line(output: str) -> str:
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    return lines[-1][:LAST_LINE_MAX] if lines else ""


def log_entry(results: list[Result]) -> tuple[str, list[str]]:
    """The `check` line text and its bullets (FORMAT §7)."""
    failed = [result for result in results if not result.passed]
    if not failed:
        return f"PASS {len(results)}/{len(results)}", []
    bullets = [
        f"{result.id} exit {result.code}: {_last_line(result.output)}".rstrip() for result in failed
    ]
    return f"FAIL {','.join(result.id for result in failed)}", bullets


def _try_number(node: Node) -> str:
    key = attempt_key(node)
    return key.removeprefix("try ") if key.startswith("try ") else str(node.tries)


def summary(node_id: str, results: list[Result]) -> str:
    failed = [result.id for result in results if not result.passed]
    total = len(results)
    if not failed:
        return f"{node_id} check PASS {total}/{total}"
    return f"{node_id} check FAIL {','.join(failed)} ({total - len(failed)}/{total} passed)"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("plan", help="plan path or slug fragment")
    parser.add_argument("node", help="node id")


def _run(args: argparse.Namespace) -> int:
    path = resolve_plan(args.plan, Path.cwd())
    plan = load_plan(path)
    if plan.header.status == "DRAFT":
        raise log.CliError("plan is DRAFT")
    node = plan.node(args.node)
    brief = load_brief(plan, node.id)
    if brief is None:
        raise log.CliError(f"node {node.id} has no brief")
    criteria = [criterion for criterion in brief.criteria if criterion.tag == "cmd"]
    for criterion in criteria:
        if criterion.command is None:
            raise log.CliError(
                f"{criterion.id}: [cmd] criterion must start with a backticked command"
            )
    results = [run_command(criterion, plan.root, TIMEOUT) for criterion in criteria]
    with plan_lock(path):
        plan = load_plan(path)
        node = plan.node(node.id)
        runs = node_paths(plan, node.id).runs
        if runs is not None:
            runs.mkdir(parents=True, exist_ok=True)
            write_atomic(runs / f"check-try{_try_number(node)}.txt", evidence_text(results))
        text, bullets = log_entry(results)
        append_log(plan, node.id, "check", text, bullets, log.today())
    print(summary(node.id, results))
    return 0 if all(result.passed for result in results) else 1


def run(args: argparse.Namespace) -> int:
    return log.guarded(_run, args)
