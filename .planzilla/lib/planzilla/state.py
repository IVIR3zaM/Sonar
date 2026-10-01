"""Plan state machine (FORMAT §3, §4, §5, §9, §13): pure functions over Graph nodes.

No IO and no clock: callers pass in the nodes, per-node brief facts, budgets, config models and,
for `resume`, the ids whose Write paths hold uncommitted changes.
"""

import re
from dataclasses import dataclass, replace

from planzilla.plan import NODE_ID, Brief, Node

IN_FLIGHT = ("BRIEFING", "RUNNING", "VERIFYING", "REPLAN")
RESUME_TEXT = "rerun at try {t}; partial edits of this try may be in the tree"
_ACTIONS = {
    "RETRY": "exec",
    "RUNNING": "exec",
    "VERIFYING": "verify",
    "BRIEFING": "brief",
    "REPLAN": "replan",
    "WAITING": "ask",
}
_AGENTS = {
    "BRIEFING": "plz-planner",
    "REPLAN": "plz-planner",
    "RUNNING": "plz-executor",
    "VERIFYING": "plz-verifier",
}
_NODE_RE = re.compile(NODE_ID)
_MODEL_RE = re.compile(r"([a-z0-9.-]+)/([a-z0-9.-]+)")


class StateError(Exception):
    """An illegal transition, failed precondition, bad structure edit or cycle (exit 2)."""


@dataclass(frozen=True)
class Facts:
    """What the state machine needs to know about a node's brief (FORMAT §5, §6)."""

    brief: bool = False
    cmd: bool = False
    verifier: bool = False
    visual: bool = False
    human: tuple[str, ...] = ()


@dataclass
class Resumed:
    nodes: list[Node]
    lines: list[str]
    logs: list[tuple[str, str]]
    status: str


def brief_facts(brief: Brief | None) -> Facts:
    """Facts of a parsed brief; `None` (not written yet) gives empty facts."""
    if brief is None:
        return Facts()
    tags = [criterion.tag for criterion in brief.criteria]
    return Facts(
        brief=True,
        cmd="cmd" in tags,
        verifier=any(tag != "cmd" for tag in tags),
        visual="visual" in tags,
        human=tuple(c.id for c in brief.criteria if c.tag == "human"),
    )


# --- §5 transitions ------------------------------------------------------------


def transition(
    node: Node, status: str, note: str | None, facts: Facts, budgets: tuple[int, int]
) -> Node:
    """The node after `set <id> <status> [--note]` (FORMAT §5 rows 1-28, redirects, budgets)."""
    tries_budget, replans_budget = budgets
    old, kind, t = node.status, node.type, node.tries
    kept = node.note if note is None else note
    cleared = "" if note is None else note

    def to(new: str, tries: int = t, rp: int = node.rp, text: str = kept) -> Node:
        return replace(node, status=new, tries=tries, rp=rp, note=text)

    def replan(tries: int = t) -> Node:
        if node.rp >= replans_budget:
            return to("BLOCKED", tries, text="blocked: " + kept.removeprefix("blocked: "))
        return to("REPLAN", tries, node.rp + 1)

    def failed(tries: int = t) -> Node:
        if kind == "exec" and tries < tries_budget:
            return to("RETRY", tries)
        return replan(tries)

    def verified(tries: int = t) -> Node:
        return to("VERIFYING", tries) if facts.verifier else to("DONE", tries, text=cleared)

    if old == status and old in IN_FLIGHT:
        return to(old)
    if old == "TODO":
        if kind in ("exec", "check") and status == "BRIEFING" and not facts.brief:
            return to("BRIEFING")
        if kind == "exec" and status == "RUNNING":
            if not facts.brief:
                raise StateError(f"illegal transition {node.id} TODO -> RUNNING: no brief")
            return to("RUNNING", t + 1)
        if kind == "check" and status in ("VERIFYING", "RETRY"):
            if not facts.brief:
                raise StateError(f"illegal transition {node.id} TODO -> {status}: no brief")
            return verified(t + 1) if status == "VERIFYING" else replan(t + 1)
        if kind == "gate" and status == "DONE":
            return to("DONE", text=cleared)
        if kind == "gate" and status == "REPLAN":
            return replan()
    elif old == "BRIEFING" and status in ("TODO", "WAITING"):
        return to(status, text=cleared if status == "TODO" else kept)
    elif old == "RUNNING":
        if status == "VERIFYING":
            return verified()
        if status == "RETRY":
            return failed()
        if status == "REPLAN":
            return replan()
    elif old == "VERIFYING":
        if status == "DONE" and facts.human:
            return to("WAITING", text="ask: " + ",".join(facts.human))
        if status == "DONE":
            return to("DONE", text=cleared)
        if status == "RETRY":
            return failed()
    elif old == "RETRY" and status == "RUNNING":
        return to("RUNNING", t + 1)
    elif old == "REPLAN" and status == "TODO":
        return to("TODO", 0, text=cleared)
    elif old == "REPLAN" and status == "WAITING":
        return to("WAITING")
    elif old == "WAITING" and node.note.startswith("ask: D") and status == "REPLAN":
        return to("REPLAN")
    elif old == "WAITING" and node.note.startswith("ask: C"):
        if status == "DONE":
            return to("DONE", text=cleared)
        if status == "RETRY":
            return failed()
    elif old == "BLOCKED":
        if status == "REPLAN":
            return to("REPLAN", rp=1)
        if status == "DONE":
            return to("DONE", text=cleared)
    raise StateError(f"illegal transition {node.id} {old} -> {status}")


def set_node(
    nodes: list[Node],
    node_id: str,
    status: str | None,
    *,
    note: str | None = None,
    add: bool = False,
    title: str | None = None,
    type: str | None = None,
    deps: str | None = None,
    model: str | None = None,
    facts: dict[str, Facts],
    budgets: tuple[int, int],
) -> tuple[list[Node], str]:
    """`set` (FORMAT §9): structure options, then the transition; returns nodes and plan status."""
    nodes = list(nodes)
    structure = add or any(value is not None for value in (title, deps, model))
    if type is not None and not add:
        raise StateError("--type needs --add")
    if status is None and not structure:
        raise StateError("STATUS is required without --add, --title, --deps or --model")
    if status is None and note is not None:
        raise StateError("--note needs STATUS")
    if note is not None:
        _check_text("--note", note)
    if add:
        if any(node.id == node_id for node in nodes):
            raise StateError(f"node {node_id} exists")
        if not _NODE_RE.fullmatch(node_id):
            raise StateError(f"bad node id {node_id!r}")
        for option, value in (("--title", title), ("--deps", deps), ("--model", model)):
            if value is None:
                raise StateError(f"--add needs {option}")
        nodes.append(Node(node_id, "", type or "exec", [], "-", "-", 0, 0, "TODO", ""))
    index = _index(nodes, node_id)
    current = nodes[index]
    if structure:
        if current.status == "DONE":
            raise StateError(f"node {node_id} is DONE")
        nodes[index] = current = _edit(current, title, deps, model)
        waves(nodes)
    if status is not None:
        if current.status in ("TODO", "RETRY") and not _deps_done(current, nodes):
            raise StateError(f"{node_id} deps are not all DONE")
        nodes[index] = transition(current, status, note, facts.get(node_id, Facts()), budgets)
    return nodes, plan_status(nodes)


def _index(nodes: list[Node], node_id: str) -> int:
    for index, node in enumerate(nodes):
        if node.id == node_id:
            return index
    raise StateError(f"unknown node {node_id}")


def _check_text(option: str, value: str) -> None:
    if "|" in value or "\n" in value:
        raise StateError(f"bad {option} {value!r}: no '|' or line break")


def _edit(node: Node, title: str | None, deps: str | None, model: str | None) -> Node:
    if title is not None:
        _check_text("--title", title)
        if not title.strip():
            raise StateError("bad --title: empty")
        node = replace(node, title=title.strip())
    if deps is not None:
        ids = [] if deps.strip() == "-" else [dep.strip() for dep in deps.split(",")]
        if any(not _NODE_RE.fullmatch(dep) for dep in ids):
            raise StateError(f"bad --deps {deps!r}: '-' or ids joined by ','")
        node = replace(node, deps=ids)
    if model is not None:
        models = _MODEL_RE.fullmatch(model)
        if not models:
            raise StateError(f"bad --model {model!r}: expected <exec>/<verify>")
        node = replace(node, exec_model=models.group(1), verify_model=models.group(2))
    return node


# --- §4 waves, §5 ready, §3 plan status ------------------------------------------


def waves(nodes: list[Node]) -> dict[str, int]:
    """wave(n) = 1 without deps, else 1 + max wave of its deps; unknown deps and cycles raise."""
    by_id = {node.id: node for node in nodes}
    for node in nodes:
        for dep in node.deps:
            if dep not in by_id:
                raise StateError(f"unknown dep {dep} of {node.id}")
    level: dict[str, int] = {}

    def visit(node_id: str, path: list[str]) -> int:
        if node_id in level:
            return level[node_id]
        if node_id in path:
            raise StateError("cycle " + " -> ".join(path[path.index(node_id) :] + [node_id]))
        path.append(node_id)
        level[node_id] = 1 + max((visit(dep, path) for dep in by_id[node_id].deps), default=0)
        path.pop()
        return level[node_id]

    for node in nodes:
        visit(node.id, [])
    return level


def _deps_done(node: Node, nodes: list[Node]) -> bool:
    done = {other.id for other in nodes if other.status == "DONE"}
    return all(dep in done for dep in node.deps)


def action(node: Node, facts: Facts) -> str | None:
    """The §5 action of a ready node, or None (DONE, BLOCKED)."""
    if node.status != "TODO":
        return _ACTIONS.get(node.status)
    if node.type == "exec":
        return "exec" if facts.brief else "brief"
    if node.type == "check":
        if not facts.brief:
            return "brief"
        return "check" if facts.cmd else "verify"
    return "ask"


def plan_status(nodes: list[Node]) -> str:
    """The derived plan status (FORMAT §3), rules in order."""
    if all(node.status == "DONE" for node in nodes):
        return "DONE"
    ready = [node for node in nodes if _deps_done(node, nodes)]
    if any(node.status in IN_FLIGHT for node in nodes) or any(
        action(node, Facts()) not in (None, "ask") for node in ready
    ):
        return "RUNNING"
    if any(node.status == "WAITING" for node in nodes) or any(
        node.type == "gate" and node.status == "TODO" for node in ready
    ):
        return "WAITING"
    return "BLOCKED"


def _model(act: str, node: Node, models: dict[str, str]) -> str:
    if act == "exec":
        return node.exec_model
    if act == "verify":
        return models["verify"] if node.verify_model == "-" else node.verify_model
    if act in ("brief", "replan"):
        return models["planner"]
    return "-"


def next_lines(nodes: list[Node], facts: dict[str, Facts], models: dict[str, str]) -> list[str]:
    """`next` lines (FORMAT §9): `<id> <action> <model>` by wave, then Graph row order."""
    level = waves(nodes)
    found = []
    for node in sorted(nodes, key=lambda node: level[node.id]):
        act = action(node, facts.get(node.id, Facts())) if _deps_done(node, nodes) else None
        if act is not None:
            found.append((act, f"{node.id} {act} {_model(act, node, models)}"))
    others = [line for act, line in found if act != "ask"]
    return others or [line for _, line in found]


def _row(node: Node) -> str:
    return f"{node.id} {node.status} try {node.tries} rp {node.rp}"


def set_line(node: Node, facts: Facts, models: dict[str, str]) -> str:
    """`set` output (FORMAT §9), with ` · dispatch <agent> <model>` for in-flight statuses."""
    agent = _AGENTS.get(node.status)
    if agent is None:
        return _row(node)
    if node.status == "VERIFYING" and facts.visual:
        agent = "plz-visual"
    return f"{_row(node)} · dispatch {agent} {_model(_ACTIONS[node.status], node, models)}"


# --- §13 resume ---------------------------------------------------------------------


def resume(nodes: list[Node], dirty: set[str]) -> Resumed:
    """Rows 29-32: RUNNING, and VERIFYING exec nodes not in `dirty`, rerun as RUNNING."""
    result, reruns, held, logs = [], [], [], []
    for node in nodes:
        if node.status == "RUNNING" or (
            node.status == "VERIFYING" and node.type == "exec" and node.id not in dirty
        ):
            node = replace(node, status="RUNNING")
            logs.append((node.id, RESUME_TEXT.format(t=node.tries)))
        if node.status in IN_FLIGHT:
            reruns.append(f"{_row(node)} · rerun")
        elif node.status in ("WAITING", "BLOCKED"):
            held.append(f"{_row(node)} · held")
        result.append(node)
    return Resumed(result, reruns + held, logs, plan_status(result))
