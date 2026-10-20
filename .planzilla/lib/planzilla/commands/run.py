"""Run one agent step on a model: `run <role> <model> <line>` prints the agent's one-line reply."""

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from planzilla import runner
from planzilla.commands._common import fail


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("role", help="planner, executor or verifier")
    parser.add_argument("model", help="model token <name>[@<effort>]")
    parser.add_argument("line", help="the one-line input, e.g. 'Plan: p · Node: N01 · Try: 1'")


def _call(argv: list[str], cli: str, cwd: str, prompt: str | None = None):
    """`subprocess.run` with captured text; a missing binary is reported as not on PATH."""
    try:
        return subprocess.run(
            argv,
            input=prompt,
            capture_output=True,
            text=True,
            errors="replace",
            cwd=cwd,
        )
    except OSError:
        return None


def run(args: argparse.Namespace) -> int:
    try:
        cli, name, effort = runner.validate(args.role, args.model, args.line)
    except ValueError as error:
        return fail(str(error), 2)
    if shutil.which(cli) is None:
        return fail(f"{cli} not found on PATH", 3)
    cwd = str(Path.cwd())
    login = _call(runner.login_argv(cli), cli, cwd)
    if login is None:
        return fail(f"{cli} not found on PATH", 3)
    if not runner.logged_in(cli, login.returncode, login.stdout):
        return fail(runner.login_hint(cli), 3)

    prompt = runner.build_prompt(args.role, args.line)
    out_dir = tempfile.mkdtemp(prefix="plz-run-") if cli == "codex" else None
    try:
        out_file = str(Path(out_dir) / "reply.txt") if out_dir else None
        argv = runner.build_argv(args.role, cli, name, effort, cwd, out_file)
        result = _call(argv, cli, cwd, prompt)
        if result is None:
            return fail(f"{cli} not found on PATH", 3)
        if result.returncode != 0:
            return fail(
                runner.exit_message(cli, result.returncode, result.stdout, result.stderr), 3
            )
        if out_file is None:
            text = result.stdout
        else:
            try:
                text = Path(out_file).read_text(encoding="utf-8", errors="replace")
            except OSError:
                text = ""
    finally:
        if out_dir:
            shutil.rmtree(out_dir, ignore_errors=True)
    reply = runner.last_line(text)
    if not reply:
        return fail(f"{cli} gave an empty reply", 3)
    print(reply)
    return 0
