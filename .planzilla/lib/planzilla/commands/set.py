"""Change a node's status or structure."""

import argparse
import datetime
from pathlib import Path

from planzilla import state
from planzilla.commands._common import (
    LockTimeout,
    ResolveError,
    fail,
    plan_lock,
    resolve_plan,
    write_plan,
)
from planzilla.config import load_config
from planzilla.plan import NODE_TYPES, STATUSES, PlanError, load_brief, load_plan


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("plan", help="plan path or slug fragment")
    parser.add_argument("id", help="node id")
    parser.add_argument("status", nargs="?", choices=STATUSES, metavar="STATUS")
    parser.add_argument("--note", help="replace the note")
    parser.add_argument("--add", action="store_true", help="append a new node")
    parser.add_argument("--title")
    parser.add_argument("--type", choices=NODE_TYPES)
    parser.add_argument("--deps", help="'-' or ids joined by ','")
    parser.add_argument("--model", help="<exec>/<verify>")


def today() -> str:
    return datetime.date.today().isoformat()


def run(args: argparse.Namespace) -> int:
    try:
        path = resolve_plan(args.plan, Path.cwd())
        with plan_lock(path):
            plan = load_plan(path)
            if plan.header.status == "DRAFT":
                return fail(f"plan {plan.name} is DRAFT", 2)
            config = load_config(plan.root)
            facts = {} if args.add else {args.id: state.brief_facts(load_brief(plan, args.id))}
            plan.nodes, status = state.set_node(
                plan.nodes,
                args.id,
                args.status,
                note=args.note,
                add=args.add,
                title=args.title,
                type=args.type,
                deps=args.deps,
                model=args.model,
                facts=facts,
                budgets=(plan.header.tries_budget, plan.header.replans_budget),
            )
            plan = write_plan(plan, status, today())
    except (ResolveError, PlanError, state.StateError) as error:
        return fail(str(error), 2)
    except LockTimeout as error:
        return fail(str(error), 3)
    node_facts = facts.get(args.id, state.Facts())
    print(state.set_line(plan.node(args.id), node_facts, config.models))
    return 0
