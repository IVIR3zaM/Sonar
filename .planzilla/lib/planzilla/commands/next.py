"""Print the next actions of a plan."""

import argparse
from pathlib import Path

from planzilla import state
from planzilla.commands._common import ResolveError, fail, resolve_plan
from planzilla.config import load_config
from planzilla.plan import PlanError, load_brief, load_plan


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("plan", help="plan path or slug fragment")


def run(args: argparse.Namespace) -> int:
    try:
        plan = load_plan(resolve_plan(args.plan, Path.cwd()))
        if plan.header.status == "DRAFT":
            return fail(f"plan {plan.name} is DRAFT", 2)
        config = load_config(plan.root)
        facts = {node.id: state.brief_facts(load_brief(plan, node.id)) for node in plan.nodes}
        lines = state.next_lines(plan.nodes, facts, config.models)
    except (ResolveError, PlanError, state.StateError) as error:
        return fail(str(error), 2)
    for line in lines:
        print(line)
    return 0
