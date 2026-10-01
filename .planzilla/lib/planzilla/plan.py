"""Plan model: parse S/M plan files and L plan directories into dataclasses (FORMAT §2-§7).

Parsing is pure (`parse_*` take text); `find_plans`, `load_*` and `save_graph` wrap the file IO.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

NODE_ID = r"N[0-9]{2,}[a-z]?"
PLAN_NAME = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2})-([a-z0-9]+(?:-[a-z0-9]+)*)")
PLAN_STATUSES = ("DRAFT", "READY", "RUNNING", "WAITING", "BLOCKED", "DONE")
STATUSES = (
    "TODO",
    "BRIEFING",
    "RUNNING",
    "VERIFYING",
    "RETRY",
    "REPLAN",
    "WAITING",
    "DONE",
    "BLOCKED",
)
NODE_TYPES = ("exec", "check", "gate")
TAGS = ("cmd", "review", "smoke", "visual", "human")
FIELDS = ("Do", "Context", "Read", "Write", "Log", "Test first", "Done when")
HEADER_KEYS = ("status", "created", "goal", "verify", "commit", "push", "budgets", "tier")
REQUIRED_HEADER_KEYS = ("status", "created", "goal", "verify", "commit")
GRAPH_HEADER = "| id | title | type | deps | model | try | rp | status | note |"
GRAPH_SEPARATOR = "|----|-------|------|------|-------|-----|----|--------|------|"
PUSH_ALIASES = {"per-node": "per-node", "none": "none", "yes": "per-node", "no": "none"}

_NODE_RE = re.compile(NODE_ID)
_MODEL_RE = re.compile(r"([a-z0-9.-]+)/([a-z0-9.-]+)")
_HEADER_LINE_RE = re.compile(r"([a-z_]+): (.*)")
_CREATED_RE = re.compile(r"([0-9]{4}-[0-9]{2}-[0-9]{2}) · updated: ([0-9]{4}-[0-9]{2}-[0-9]{2})")
_BUDGETS_RE = re.compile(r"([0-9]+) tries per brief · ([0-9]+) replans per node")
_DECISION_RE = re.compile(r"- (D[0-9]+) (.*)")
_NODE_HEADING_RE = re.compile(rf"({NODE_ID}) (.+)")
_CRITERION_RE = re.compile(r"- (C[0-9]+)(?: (.*))?")
_TAG_RE = re.compile(r"\[([^\]]*)\] ?(.*)")
_LOG_HEADING_RE = re.compile(r"##+ ")
_LOG_STAMP_RE = re.compile(r" · [0-9]{4}-[0-9]{2}-[0-9]{2}(?: [0-9:]+)?$")
_COMMAND_RE = re.compile(r"`([^`]+)`")
_BACKTICKED_RE = re.compile(r"`([^`]*)`")


class PlanError(Exception):
    """A plan, brief or config parse error, pointing at a file and a 1-based line."""

    def __init__(self, file: Path | str, line: int, message: str) -> None:
        super().__init__(f"{file}:{line}: {message}")
        self.file = Path(file)
        self.line = line
        self.message = message


@dataclass
class Node:
    """One Graph row (FORMAT §4). `line`/`source` locate the row in the graph file."""

    id: str
    title: str
    type: str
    deps: list[str]
    exec_model: str
    verify_model: str
    tries: int
    rp: int
    status: str
    note: str
    line: int | None = field(default=None, compare=False)
    source: str | None = field(default=None, compare=False, repr=False)


@dataclass
class Header:
    """Plan header lines (FORMAT §3); `push`/`tier` are None when absent."""

    status: str
    created: str
    updated: str
    goal: str
    verify: str
    commit: str
    push: str | None
    tries_budget: int
    replans_budget: int
    tier: str | None
    lines: dict[str, int] = field(default_factory=dict, compare=False)


@dataclass
class Decision:
    id: str
    text: str
    state: str
    line: int


@dataclass
class Plan:
    path: Path
    graph_file: Path
    text: str
    title: str
    header: Header
    decisions: list[Decision]
    nodes: list[Node]
    graph_line: int
    graph_end: int

    @property
    def is_dir(self) -> bool:
        return self.path != self.graph_file

    @property
    def name(self) -> str:
        return self.path.name if self.is_dir else self.path.stem

    @property
    def slug(self) -> str:
        match = PLAN_NAME.fullmatch(self.name)
        return match.group(2) if match else self.name

    @property
    def root(self) -> Path:
        return self.path.parent.parent

    @property
    def tier(self) -> str:
        return "L" if self.is_dir else self.header.tier or "M"

    def node(self, node_id: str) -> Node:
        for node in self.nodes:
            if node.id == node_id:
                return node
        raise PlanError(self.graph_file, self.graph_line, f"unknown node {node_id}")


@dataclass
class Criterion:
    id: str
    tag: str | None
    text: str
    command: str | None
    line: int


@dataclass
class Brief:
    """A node brief (FORMAT §6). `fields` holds each field's lines verbatim, label included."""

    id: str
    title: str
    file: Path
    line: int
    text: str
    fields: dict[str, str]
    field_lines: dict[str, int]
    write: list[str] | None
    criteria: list[Criterion]

    def value(self, label: str) -> str | None:
        """The field's value: text after the label plus the following lines, stripped."""
        block = self.fields.get(label)
        return None if block is None else block[len(label) + 1 :].strip()


@dataclass
class NodePaths:
    plan: Path
    graph: Path
    brief: Path
    log: Path
    runs: Path | None


# --- files -----------------------------------------------------------------


def _read(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def find_plans(repo: Path) -> list[Path]:
    """Plans in `<repo>/.plan/`: L directories and S/M `.md` files, sorted by name."""
    plan_dir = repo / ".plan"
    if not plan_dir.is_dir():
        return []
    found = []
    for path in plan_dir.iterdir():
        if path.is_dir() and PLAN_NAME.fullmatch(path.name):
            found.append(path)
        elif path.is_file() and path.suffix == ".md" and PLAN_NAME.fullmatch(path.stem):
            found.append(path)
    return sorted(found, key=lambda p: p.name)


def load_plan(path: Path) -> Plan:
    """Load an L plan directory or an S/M plan file."""
    graph_file = path / "plan.md" if path.is_dir() else path
    if not graph_file.is_file():
        raise PlanError(graph_file, 1, "plan file not found")
    return parse_plan(_read(graph_file), path, graph_file)


def load_brief(plan: Plan, node_id: str) -> Brief | None:
    """The node's brief, or None when it is not written yet (just-in-time briefing)."""
    node = plan.node(node_id)
    if plan.is_dir:
        file = plan.path / "nodes" / f"{node_id}.md"
        if not file.is_file():
            return None
        lines = _read(file).split("\n")
        return parse_brief(lines, 1, file, node, "# ")
    lines = plan.text.split("\n")
    for index, line in enumerate(lines):
        match = _NODE_HEADING_RE.fullmatch(line[3:]) if line.startswith("## ") else None
        if match and match.group(1) == node_id:
            end = index + 1
            while end < len(lines) and not lines[end].startswith("## "):
                end += 1
            return parse_brief(lines[index:end], index + 1, plan.graph_file, node, "## ")
    return None


def node_paths(plan: Plan, node_id: str) -> NodePaths:
    """Where a node's brief, log and evidence live (FORMAT §2, §7)."""
    if not plan.is_dir:
        return NodePaths(plan.path, plan.graph_file, plan.path, plan.path, None)
    return NodePaths(
        plan.path,
        plan.graph_file,
        plan.path / "nodes" / f"{node_id}.md",
        plan.path / "log" / f"{node_id}.md",
        plan.path / "runs" / node_id,
    )


def save_graph(plan: Plan) -> Plan:
    """Rewrite only the changed (or added) Graph rows, atomically; return the reloaded plan."""
    text = render_graph(plan)
    if text != plan.text:
        tmp = plan.graph_file.with_name(plan.graph_file.name + ".tmp")
        tmp.write_bytes(text.encode("utf-8"))
        tmp.replace(plan.graph_file)
    return parse_plan(text, plan.path, plan.graph_file)


# --- plan parsing ----------------------------------------------------------


def parse_plan(text: str, path: Path, graph_file: Path) -> Plan:
    """Parse the text of an S/M plan file (`path == graph_file`) or of an L `plan.md`."""
    lines = text.split("\n")
    if not lines[0].startswith("# ") or not lines[0][2:].strip():
        raise PlanError(graph_file, 1, "first line must be '# <title>'")
    header = _parse_header(lines, graph_file, single_file=path == graph_file)
    sections = _sections(lines, graph_file, single_file=path == graph_file)
    if "Graph" not in sections:
        raise PlanError(graph_file, 1, "missing '## Graph' section")
    decisions = []
    if "Decisions" in sections:
        start, end = sections["Decisions"]
        decisions = _parse_decisions(lines, start, end, graph_file)
    start, end = sections["Graph"]
    nodes, graph_end = _parse_graph(lines, start, end, graph_file)
    return Plan(
        path=path,
        graph_file=graph_file,
        text=text,
        title=lines[0][2:].strip(),
        header=header,
        decisions=decisions,
        nodes=nodes,
        graph_line=start + 1,
        graph_end=graph_end,
    )


def _parse_header(lines: list[str], file: Path, single_file: bool) -> Header:
    values: dict[str, str] = {}
    numbers: dict[str, int] = {}
    last = -1
    index = 1
    while index < len(lines) and lines[index] != "":
        number = index + 1
        match = _HEADER_LINE_RE.fullmatch(lines[index])
        if not match:
            raise PlanError(file, number, f"bad header line: {lines[index]!r}")
        key, value = match.group(1), match.group(2).strip()
        if key not in HEADER_KEYS:
            raise PlanError(file, number, f"unknown header key: {key}")
        if key in values:
            raise PlanError(file, number, f"repeated header key: {key}")
        if HEADER_KEYS.index(key) < last:
            raise PlanError(file, number, f"header key out of order: {key}")
        last = HEADER_KEYS.index(key)
        values[key], numbers[key] = value, number
        index += 1
    for key in REQUIRED_HEADER_KEYS:
        if key not in values:
            raise PlanError(file, index + 1, f"missing header key: {key}")

    def bad(key: str) -> PlanError:
        return PlanError(file, numbers[key], f"bad {key} value: {values[key]!r}")

    if values["status"] not in PLAN_STATUSES:
        raise bad("status")
    created = _CREATED_RE.fullmatch(values["created"])
    if not created:
        raise bad("created")
    for key in ("goal", "verify"):
        if not values[key]:
            raise bad(key)
    if values["commit"] not in ("per-node", "none"):
        raise bad("commit")
    push = values.get("push")
    if push is not None:
        if push not in PUSH_ALIASES:
            raise bad("push")
        push = PUSH_ALIASES[push]
    tries_budget, replans_budget = 2, 2
    if "budgets" in values:
        budgets = _BUDGETS_RE.fullmatch(values["budgets"])
        if not budgets:
            raise bad("budgets")
        tries_budget, replans_budget = int(budgets.group(1)), int(budgets.group(2))
    tier = values.get("tier")
    if tier is not None and (not single_file or tier not in ("S", "M")):
        raise bad("tier")
    return Header(
        status=values["status"],
        created=created.group(1),
        updated=created.group(2),
        goal=values["goal"],
        verify=values["verify"],
        commit=values["commit"],
        push=push,
        tries_budget=tries_budget,
        replans_budget=replans_budget,
        tier=tier,
        lines=numbers,
    )


def _sections(lines: list[str], file: Path, single_file: bool) -> dict[str, tuple[int, int]]:
    """Map section kinds to (heading index, end index). S/M: enforce §2 names and order."""
    rank = {"Intent": 1, "Decisions": 2, "Graph": 3, "node": 4, "Log": 5}
    headings = [i for i, line in enumerate(lines) if line.startswith("## ")]
    sections: dict[str, tuple[int, int]] = {}
    last = 0
    for position, index in enumerate(headings):
        name = lines[index][3:].strip()
        end = headings[position + 1] if position + 1 < len(headings) else len(lines)
        kind = name if name in rank and name != "node" else None
        if kind is None and _NODE_HEADING_RE.fullmatch(name):
            kind = "node"
        if not single_file:
            if kind in ("Decisions", "Graph") and kind not in sections:
                sections[kind] = (index, end)
            continue
        if kind is None:
            raise PlanError(file, index + 1, f"unexpected section: ## {name}")
        if kind in sections or rank[kind] < last:
            raise PlanError(file, index + 1, f"section out of order: ## {name}")
        last = rank[kind]
        if kind != "node":
            sections[kind] = (index, end)
    return sections


def _parse_decisions(lines: list[str], start: int, end: int, file: Path) -> list[Decision]:
    decisions = []
    for index in range(start + 1, end):
        match = _DECISION_RE.fullmatch(lines[index])
        if not match:
            continue
        body = match.group(2)
        text, sep, rest = body.rpartition(" | ")
        state = re.match(r"[a-z]*", rest).group(0) if sep else ""
        if state not in ("proposed", "confirmed"):
            raise PlanError(
                file, index + 1, f"decision {match.group(1)} needs '| proposed|confirmed'"
            )
        decisions.append(Decision(match.group(1), text, state, index + 1))
    return decisions


def _parse_graph(lines: list[str], start: int, end: int, file: Path) -> tuple[list[Node], int]:
    """Parse the Graph table; return the nodes and the 1-based line of the last table line."""
    expected = ["", GRAPH_HEADER, GRAPH_SEPARATOR]
    for offset, want in enumerate(expected, 1):
        index = start + offset
        if index >= end or lines[index] != want:
            raise PlanError(file, index + 1, f"Graph table: expected {want!r}")
    nodes: list[Node] = []
    seen: set[str] = set()
    index = start + len(expected) + 1
    while index < end and lines[index].startswith("|"):
        node = parse_row(lines[index], file, index + 1)
        if node.id in seen:
            raise PlanError(file, index + 1, f"duplicate node id {node.id}")
        seen.add(node.id)
        nodes.append(node)
        index += 1
    if index < end and lines[index] != "":
        raise PlanError(file, index + 1, "Graph table must end with a blank line")
    return nodes, index


def parse_row(line: str, file: Path, number: int) -> Node:
    """Parse one Graph row (FORMAT §4)."""
    if not line.startswith("| ") or not line.endswith("|"):
        raise PlanError(file, number, "Graph row must look like '| <id> | ... |'")
    cells = [cell.strip() for cell in line[1:-1].split("|")]
    if len(cells) != 9:
        raise PlanError(file, number, f"Graph row needs 9 cells, got {len(cells)}")
    node_id, title, node_type, deps_cell, model, tries, rp, status, note = cells

    def bad(column: str, value: str) -> PlanError:
        return PlanError(file, number, f"bad {column} {value!r}")

    if not _NODE_RE.fullmatch(node_id):
        raise bad("id", node_id)
    if not title:
        raise bad("title", title)
    if node_type not in NODE_TYPES:
        raise bad("type", node_type)
    deps = [] if deps_cell == "-" else [dep.strip() for dep in deps_cell.split(",")]
    if any(not _NODE_RE.fullmatch(dep) for dep in deps):
        raise bad("deps", deps_cell)
    models = _MODEL_RE.fullmatch(model)
    if not models:
        raise bad("model", model)
    for column, value in (("try", tries), ("rp", rp)):
        if not value.isdigit():
            raise bad(column, value)
    if status not in STATUSES:
        raise bad("status", status)
    return Node(
        id=node_id,
        title=title,
        type=node_type,
        deps=deps,
        exec_model=models.group(1),
        verify_model=models.group(2),
        tries=int(tries),
        rp=int(rp),
        status=status,
        note=note,
        line=number,
        source=line,
    )


def format_row(node: Node) -> str:
    """A Graph row as written: `| <value> |` cells, deps joined by `,`, empty note `| |`."""
    cells = [
        node.id,
        node.title,
        node.type,
        ",".join(node.deps) or "-",
        f"{node.exec_model}/{node.verify_model}",
        str(node.tries),
        str(node.rp),
        node.status,
        node.note,
    ]
    return "|" + "".join(f" {cell} |" if cell else " |" for cell in cells)


def render_graph(plan: Plan) -> str:
    """The plan file text with changed rows rewritten and new rows appended; all else kept."""
    lines = plan.text.split("\n")
    added = []
    for node in plan.nodes:
        if node.line is None or node.source is None:
            added.append(format_row(node))
        elif parse_row(node.source, plan.graph_file, node.line) != node:
            lines[node.line - 1] = format_row(node)
    lines[plan.graph_end : plan.graph_end] = added
    return "\n".join(lines)


def render_plan(plan: Plan, status: str, today: str) -> str:
    """`render_graph` text with only the header `status:` value and `updated:` date replaced."""
    lines = render_graph(plan).split("\n")
    lines[plan.header.lines["status"] - 1] = f"status: {status}"
    lines[plan.header.lines["created"] - 1] = f"created: {plan.header.created} · updated: {today}"
    return "\n".join(lines)


def attempt_key(node: Node) -> str:
    """The log attempt key of a node (FORMAT §7): `brief`, `replan <r>` or `try <n>`."""
    if node.status == "BRIEFING":
        return "brief"
    if node.status == "REPLAN":
        return f"replan {node.rp}"
    return f"try {node.tries + 1 if node.status in ('TODO', 'RETRY') else node.tries}"


def append_entry(log_text: str, heading: str, kind: str, text: str, bullets: list[str]) -> str:
    """`log_text` plus one entry (FORMAT §7); the heading is added only when its key is new."""
    if not log_text.endswith("\n"):
        log_text += "\n"
    last = next(
        (line for line in reversed(log_text.split("\n")) if _LOG_HEADING_RE.match(line)), ""
    )
    if _heading_key(last) != _heading_key(heading):
        log_text += f"\n{heading}\n"
    entry = [f"{kind}: {text}", *(f"- {bullet}" for bullet in bullets)]
    return log_text + "\n".join(entry) + "\n"


def _heading_key(heading: str) -> str:
    """A log heading without its `#`s and its trailing ` · <date>[ <time>]`."""
    return _LOG_STAMP_RE.sub("", heading.lstrip("#").strip())


# --- brief parsing ---------------------------------------------------------


def parse_brief(lines: list[str], first: int, file: Path, node: Node, prefix: str) -> Brief:
    """Parse a brief: `lines[0]` is its heading (`# ` in L, `## ` in S/M) at line `first`."""
    while len(lines) > 1 and not lines[-1].strip():
        lines = lines[:-1]
    heading = _NODE_HEADING_RE.fullmatch(lines[0][len(prefix) :])
    if not lines[0].startswith(prefix) or not heading or heading.group(1) != node.id:
        raise PlanError(file, first, f"brief must start with '{prefix}{node.id} <title>'")
    blocks: dict[str, list[str]] = {}
    field_lines: dict[str, int] = {}
    current = None
    for offset, line in enumerate(lines[1:], 1):
        label = next((f for f in FIELDS if line.startswith(f + ":")), None)
        if label is not None:
            if current is not None and FIELDS.index(label) <= FIELDS.index(current):
                raise PlanError(file, first + offset, f"field out of order: {label}:")
            current = label
            blocks[label] = []
            field_lines[label] = first + offset
        elif current is None and line.strip():
            raise PlanError(file, first + offset, "text before the first field")
        if current is not None:
            blocks[current].append(line)
    for label in ("Do", "Done when"):
        if label not in blocks:
            raise PlanError(file, first, f"brief {node.id} has no '{label}:' field")
    fields = {label: "\n".join(block).rstrip() for label, block in blocks.items()}
    write = _parse_write(blocks.get("Write"), field_lines.get("Write", first), file, node)
    criteria = _parse_criteria(blocks["Done when"], field_lines["Done when"], file)
    return Brief(
        id=node.id,
        title=heading.group(2),
        file=file,
        line=first,
        text="\n".join(lines),
        fields=fields,
        field_lines=field_lines,
        write=write,
        criteria=criteria,
    )


def _parse_write(block: list[str] | None, number: int, file: Path, node: Node) -> list[str] | None:
    if block is None:
        if node.type == "exec":
            raise PlanError(file, number, f"exec node {node.id} needs a 'Write:' field")
        return None
    value = "\n".join(block)[len("Write:") :].strip()
    if value == "-":
        return []
    if node.type != "exec":
        raise PlanError(file, number, f"{node.type} node {node.id}: 'Write:' must be absent or -")
    outside = _BACKTICKED_RE.sub("", value)
    items = _BACKTICKED_RE.findall(value)
    if not items or outside.replace(",", "").strip():
        raise PlanError(file, number, "Write: items must be backticked paths separated by ','")
    for item in items:
        problem = _write_path_problem(item)
        if problem:
            raise PlanError(file, number, f"Write path {item!r}: {problem}")
    return items


def _write_path_problem(item: str) -> str | None:
    if not item:
        return "empty"
    if item.startswith("/"):
        return "must be repo-relative"
    if "\\" in item:
        return "no backslashes"
    if any(char in item for char in "?[]{}"):
        return "no ?, [...] or {...}"
    segments = item[:-1].split("/") if item.endswith("/") else item.split("/")
    for segment in segments:
        if segment in ("", ".", ".."):
            return "no empty, '.' or '..' segments"
        if "**" in segment and segment != "**":
            return "'**' must be a whole segment"
    return None


def _parse_criteria(block: list[str], first: int, file: Path) -> list[Criterion]:
    criteria: list[Criterion] = []
    parts: list[str] = []

    def close() -> None:
        if criteria:
            criteria[-1].text = " ".join(parts)
            criterion = criteria[-1]
            if criterion.tag == "cmd":
                match = _COMMAND_RE.match(criterion.text)
                criterion.command = match.group(1) if match else None

    rest = [block[0][len("Done when:") :]] + block[1:]
    for offset, line in enumerate(rest):
        number = first + offset
        match = _CRITERION_RE.fullmatch(line)
        if match:
            close()
            criterion_id, body = match.group(1), (match.group(2) or "").strip()
            if any(c.id == criterion_id for c in criteria):
                raise PlanError(file, number, f"duplicate criterion {criterion_id}")
            tagged = _TAG_RE.fullmatch(body)
            tag, body = (tagged.group(1), tagged.group(2).strip()) if tagged else (None, body)
            criteria.append(Criterion(criterion_id, tag, body, None, number))
            parts = [body]
        elif line.startswith("  ") and line.strip() and criteria:
            parts.append(line.strip())
        elif line.strip():
            raise PlanError(file, number, "Done when: expected '- C<n> [<tag>] <text>'")
    close()
    return criteria
