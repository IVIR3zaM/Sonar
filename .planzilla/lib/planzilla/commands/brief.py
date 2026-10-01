"""Print a node's brief."""

import argparse
import re
from pathlib import Path

from planzilla.commands import log
from planzilla.commands._common import resolve_plan
from planzilla.config import Config, load_config
from planzilla.plan import Brief, Node, Plan, load_brief, load_plan

RERUN_NOTICE = (
    "Rerun: this try was interrupted; the tree may hold its partial edits. Continue from them."
)
_ASK_DECISION_RE = re.compile(r"ask: (D[0-9]+)")
_ASK_CRITERIA_RE = re.compile(r"ask: (C[0-9]+(?:,C[0-9]+)*)")


def executor_text(plan: Plan, node: Node, brief: Brief, config: Config) -> str:
    """The brief, the last findings on a retry, the rerun notice, then the fast verify command."""
    entries = log.parse_entries(log.read_log(plan, node.id), plan.is_dir, node.id)
    parts = [brief.text]
    if node.tries >= 2:
        findings = log.last_findings(entries)
        if findings:
            parts += ["", f"## Findings (try {node.tries - 1})", *findings]
    if log.has_rerun_marker(entries, node.tries):
        parts += ["", RERUN_NOTICE]
    fast = config.verify_fast if config.verify_fast != config.verify else plan.header.verify
    parts += ["", f"Verify: {fast}"]
    return "\n".join(parts)


def verify_text(brief: Brief, config: Config) -> str:
    """What a cold verifier sees: heading, Write and Done when; never findings or logs."""
    parts = [brief.text.split("\n")[0]]
    parts += [brief.fields[label] for label in ("Write", "Done when") if label in brief.fields]
    if config.visual_recipe and any(c.tag == "visual" for c in brief.criteria):
        parts.append(f"Visual recipe: {config.visual_recipe}")
    return "\n".join(parts)


def _decision_line(plan: Plan, decision_id: str) -> str:
    for decision in plan.decisions:
        if decision.id == decision_id:
            line = plan.text.split("\n")[decision.line - 1]
            return line[len(f"- {decision_id} ") :]
    raise log.CliError(f"unknown decision {decision_id}")


def ask_line(plan: Plan, node: Node) -> str:
    """The one line the human round shows for a WAITING, BLOCKED or gate node."""
    if node.status == "WAITING":
        decision = _ASK_DECISION_RE.fullmatch(node.note)
        if decision:
            return f"{node.id} {decision.group(1)}: {_decision_line(plan, decision.group(1))}"
        criteria = _ASK_CRITERIA_RE.fullmatch(node.note)
        if criteria:
            brief = _need_brief(plan, node)
            texts = {c.id: c.text for c in brief.criteria}
            ids = criteria.group(1).split(",")
            missing = [i for i in ids if i not in texts]
            if missing:
                raise log.CliError(f"node {node.id} has no criterion {missing[0]}")
            return f"{node.id} human " + " · ".join(f"{i}: {texts[i]}" for i in ids)
    elif node.status == "BLOCKED":
        return f"{node.id} blocked: {node.note.removeprefix('blocked: ')}"
    elif node.type == "gate" and node.status == "TODO":
        brief = _need_brief(plan, node)
        return f"{node.id} gate: " + " · ".join([node.title, *(c.text for c in brief.criteria)])
    raise log.CliError(f"node {node.id} has nothing to ask ({node.status})")


def _need_brief(plan: Plan, node: Node) -> Brief:
    brief = load_brief(plan, node.id)
    if brief is None:
        raise log.CliError(f"node {node.id} has no brief")
    return brief


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("plan", help="plan path or slug fragment")
    parser.add_argument("node", help="node id")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--verify", action="store_true", help="cold verifier view")
    mode.add_argument("--ask", action="store_true", help="the one-line question for the human")


def _run(args: argparse.Namespace) -> int:
    plan = load_plan(resolve_plan(args.plan, Path.cwd()))
    node = plan.node(args.node)
    if args.ask:
        text = ask_line(plan, node)
    else:
        brief = _need_brief(plan, node)
        config = load_config(plan.root)
        text = (
            verify_text(brief, config) if args.verify else executor_text(plan, node, brief, config)
        )
    print(text)
    return 0


def run(args: argparse.Namespace) -> int:
    return log.guarded(_run, args)
