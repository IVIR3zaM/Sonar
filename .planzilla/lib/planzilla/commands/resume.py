"""Report in-flight and held nodes of a plan."""

import argparse
import datetime
from pathlib import Path

from planzilla import state
from planzilla.commands._common import (
    GitError,
    LockTimeout,
    ResolveError,
    append_log,
    fail,
    load_brief,
    load_config,
    load_plan,
    plan_lock,
    resolve_plan,
    uncommitted,
    write_plan,
)
from planzilla.config import plan_policy
from planzilla.plan import PlanError


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("plan", help="plan path or slug fragment")


def today() -> str:
    return datetime.date.today().isoformat()


def run(args: argparse.Namespace) -> int:
    day = today()
    try:
        path = resolve_plan(args.plan, Path.cwd())
        with plan_lock(path):
            plan = load_plan(path)
            if plan.header.status == "DRAFT":
                return fail(f"plan {plan.name} is DRAFT", 2)
            plan_policy(load_config(plan.root), plan)
            if plan.header.status == "DONE":
                return 0
            dirty = set()
            for node in plan.nodes:
                if node.status == "VERIFYING" and node.type == "exec":
                    brief = load_brief(plan, node.id)
                    if uncommitted(plan.root, brief.write if brief else []):
                        dirty.add(node.id)
            result = state.resume(plan.nodes, dirty)
            plan.nodes = result.nodes
            plan = write_plan(plan, result.status, day)
            for node_id, text in result.logs:
                append_log(plan, node_id, "resume", text, [], day)
    except (ResolveError, PlanError) as error:
        return fail(str(error), 2)
    except (LockTimeout, GitError) as error:
        return fail(str(error), 3)
    for line in result.lines:
        print(line)
    return 0
