"""Pure per-node view of a plan for `status`, `stats` and `serve` (FORMAT §12).

No IO here: the caller reads the plan, the logs and `git log` and passes them in as plain data,
together with `now` (seconds since the epoch).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from planzilla.plan import Node, Plan
from planzilla.state import waves

LAST_MAX = 80

VIEWS = {
    "TODO": "todo",
    "BRIEFING": "planning",
    "RUNNING": "executing",
    "VERIFYING": "verifying",
    "RETRY": "retry",
    "REPLAN": "replanning",
    "WAITING": "waiting",
    "DONE": "done",
    "BLOCKED": "blocked",
}

Commit = tuple[int, str]
"""One `git log --format='%ct %s'` entry: commit time in seconds and subject."""


@dataclass(frozen=True)
class NodeView:
    id: str
    title: str
    type: str
    wave: int
    status: str
    view: str
    tries: int
    rp: int
    note: str
    last: str
    elapsed: int | None


@dataclass(frozen=True)
class Report:
    slug: str
    title: str
    status: str
    tier: str
    updated: str
    done: int
    total: int
    elapsed: int | None
    waves: list[tuple[int, list[NodeView]]]
    tries: int
    replans: int
    blocked: int
    commits: int


def format_elapsed(seconds: int | None) -> str:
    """`<h>h<mm>m` from one hour, `<m>m` from one minute, else `<s>s`; unknown is `-`."""
    if seconds is None:
        return "-"
    if seconds >= 3600:
        return f"{seconds // 3600}h{seconds % 3600 // 60:02d}m"
    if seconds >= 60:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def parse_git_log(text: str) -> list[Commit]:
    """Parse `git log --format='%ct %s'` output; lines that do not start with a time are skipped."""
    commits = []
    for line in text.split("\n"):
        stamp, _, subject = line.partition(" ")
        if stamp.isdigit():
            commits.append((int(stamp), subject))
    return commits


def last_line(lines: Sequence[str]) -> str:
    """The last non-blank line cut to 80 characters with `…`, or `-`."""
    for line in reversed(lines):
        text = line.strip()
        if text:
            return text if len(text) <= LAST_MAX else text[: LAST_MAX - 1] + "…"
    return "-"


def _entries(text: str, is_dir: bool, node_id: str) -> list[tuple[str, list[str]]]:
    """The node's log entries as (attempt key, lines under the heading), in order (FORMAT §7).
    L: `text` is the node's log file; S/M: the plan file, whose `## Log` holds `### <id> <key>`."""
    lines = text.split("\n")
    if not is_dir:
        lines = lines[lines.index("## Log") + 1 :] if "## Log" in lines else []
    prefix = "## " if is_dir else "### "
    entries: list[tuple[str, list[str]]] = []
    current: list[str] | None = None
    for line in lines:
        if line.startswith(prefix):
            key = line[len(prefix) :].split(" · ")[0].strip()
            owner, _, key = key.partition(" ") if not is_dir else (node_id, "", key)
            current = None
            if owner == node_id:
                current = []
                entries.append((key, current))
        elif current is not None:
            current.append(line)
    return entries


def _node_commit(commits: Sequence[Commit], slug: str, node_id: str) -> int | None:
    """Time of the newest commit whose subject starts with `<slug> <id>: `."""
    prefix = f"{slug} {node_id}: "
    times = [when for when, subject in commits if subject.startswith(prefix)]
    return max(times) if times else None


def _elapsed(
    node: Node,
    own: int | None,
    commits_by_id: Mapping[str, int | None],
    oldest: int | None,
    now: int,
) -> int | None:
    if node.status == "TODO":
        return None
    if node.deps:
        known = [t for dep in node.deps if (t := commits_by_id.get(dep)) is not None]
        start = max(known) if known else None
    else:
        start = oldest
    if start is None:
        return None
    if node.status == "DONE":
        return None if own is None else own - start
    return now - start


def build_report(
    plan: Plan, logs: Mapping[str, str], commits: Sequence[Commit], now: int
) -> Report:
    """The per-node view. `logs` maps node id to the text `parse_entries` reads (L: the node's
    log file, S/M: the plan file); `commits` is the plan path's git log, newest first."""
    level = waves(plan.nodes)
    own = {node.id: _node_commit(commits, plan.slug, node.id) for node in plan.nodes}
    oldest = min((when for when, _ in commits), default=None)
    done = sum(node.status == "DONE" for node in plan.nodes)
    tries = 0
    grouped: dict[int, list[NodeView]] = {}
    for node in plan.nodes:
        entries = _entries(logs.get(node.id, ""), plan.is_dir, node.id)
        tries += sum(key.startswith("try ") for key, _ in entries)
        view = NodeView(
            id=node.id,
            title=node.title,
            type=node.type,
            wave=level[node.id],
            status=node.status,
            view=VIEWS[node.status],
            tries=node.tries,
            rp=node.rp,
            note=node.note,
            last=last_line([line for _, lines in entries for line in lines]),
            elapsed=_elapsed(node, own[node.id], own, oldest, now),
        )
        grouped.setdefault(view.wave, []).append(view)
    finished = bool(plan.nodes) and done == len(plan.nodes)
    node_times = [t for t in own.values() if t is not None]
    end = (max(node_times) if node_times else None) if finished else now
    return Report(
        slug=plan.slug,
        title=plan.title,
        status=plan.header.status,
        tier=plan.tier,
        updated=plan.header.updated,
        done=done,
        total=len(plan.nodes),
        elapsed=None if end is None or oldest is None else end - oldest,
        waves=sorted(grouped.items()),
        tries=tries,
        replans=sum(node.rp for node in plan.nodes),
        blocked=sum(node.status == "BLOCKED" for node in plan.nodes),
        commits=_count_node_commits(commits, plan),
    )


def _count_node_commits(commits: Sequence[Commit], plan: Plan) -> int:
    """Commits whose subject starts with `<slug> <id>: ` of a node of the plan."""
    prefixes = tuple(f"{plan.slug} {node.id}: " for node in plan.nodes)
    return sum(subject.startswith(prefixes) for _, subject in commits)


def format_status(report: Report) -> str:
    """The §12 `status` text."""
    lines = [
        f"{report.title} · {report.status} · {report.done}/{report.total} done"
        f" · {format_elapsed(report.elapsed)}"
    ]
    for wave, views in report.waves:
        lines.append(f"wave {wave}")
        for v in views:
            lines.append(
                f"  {v.id} {v.view} · {v.title} · try {v.tries} rp {v.rp}"
                f" · {format_elapsed(v.elapsed)} · {v.note or '-'} · {v.last}"
            )
    return "\n".join(lines)


def format_stats(report: Report) -> str:
    """The §12 `stats` line."""
    return (
        f"nodes {report.total} · done {report.done} · tries {report.tries}"
        f" · replans {report.replans} · blocked {report.blocked} · commits {report.commits}"
        f" · wall {format_elapsed(report.elapsed)}"
    )
