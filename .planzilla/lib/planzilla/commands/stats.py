"""Print the totals of a plan.

Read-only: no lock, no write (FORMAT §12).
"""

import argparse
from pathlib import Path

from planzilla.commands._common import ResolveError, fail
from planzilla.commands.status import load_report
from planzilla.plan import PlanError
from planzilla.report import format_stats
from planzilla.state import StateError


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("plan", help="plan path or slug fragment")


def run(args: argparse.Namespace) -> int:
    try:
        report = load_report(args.plan, Path.cwd())
    except (ResolveError, PlanError, StateError) as error:
        return fail(str(error), 2)
    print(format_stats(report))
    return 0
