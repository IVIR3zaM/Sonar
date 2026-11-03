"""Resolve plan policy against supplied host facts and invoke a separate named role."""

import argparse
import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

from planzilla import resolver, runner
from planzilla.commands import run as run_command
from planzilla.commands._common import (
    ResolveError,
    fail,
    load_config,
    load_plan,
    resolve_plan,
)
from planzilla.config import Policy, plan_policy
from planzilla.plan import PlanError
from planzilla.providers import HARNESS_ROUTES


@dataclass(frozen=True)
class NativeAdapter:
    """One observed callable schema and its host-owned invocation bridge.

    Schema values are accepted string enums, or None for an unrestricted string field.
    The bridge must return the completed role reply; job waiting belongs to the host.
    Non-Codex hosts supply their actual field names and fixed controls explicitly.
    No adapter, schema or fixture constitutes evidence of live access by itself.
    """

    route: str
    schema: Mapping[str, tuple[object, ...] | None]
    invoke: Callable[[dict[str, object]], str]
    model_field: str = "model"
    effort_field: str = "reasoning_effort"
    role_field: str = "task_name"
    input_field: str = "message"
    fixed: Mapping[str, object] = field(default_factory=lambda: {"fork_turns": "none"})
    delivery_id: str | None = None

    def accepts(self, key: str, value: object) -> bool:
        return key in self.schema and (
            isinstance(value, str) if self.schema[key] is None else value in self.schema[key]
        )

    def fields(self, role: str, model: str, effort: str | None, line: str) -> dict[str, object]:
        fields = dict(self.fixed)
        fields[self.model_field] = model
        if effort is not None:
            fields[self.effort_field] = effort
        fields[self.role_field] = f"plz-{role}"
        fields[self.input_field] = (
            "Read and follow repository AGENTS.md/CLAUDE.md instructions.\n"
            + runner.build_prompt(role, line)
        )
        return fields


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("plan")
    parser.add_argument("role", choices=runner.ROLES)
    parser.add_argument("line")
    parser.add_argument("--actual-harness", required=True, choices=tuple(HARNESS_ROUTES))
    parser.add_argument(
        "--facts",
        required=True,
        help="path to a UTF-8 JSON file holding an array of Capability records (FORMAT §9)",
    )
    parser.add_argument(
        "--node", help="use the Graph phase token; requires matching in-flight status"
    )
    parser.add_argument("--model", help="explicit request token, still restricted by plan policy")
    parser.add_argument(
        "--allow-low",
        action="store_true",
        help="permit low effort mapped from a portable alias or a role default",
    )
    parser.add_argument("--record", help="write selection or handoff records as JSON")


def _adapter(cap: resolver.Capability, adapters: tuple[NativeAdapter, ...]) -> NativeAdapter | None:
    return next(
        (
            a
            for a in adapters
            if a.route == cap.route and (a.delivery_id is None or a.delivery_id == cap.delivery_id)
        ),
        None,
    )


def _capabilities(
    capabilities: tuple[resolver.Capability, ...],
    adapters: tuple[NativeAdapter, ...],
    context: resolver.Context,
    requests: tuple[resolver.Request, ...],
    lines: tuple[str, ...],
) -> tuple[resolver.Capability, ...]:
    """Reconcile claimed controls with the actual callable schema before resolution."""
    result = []
    for cap in capabilities:
        if cap.failure is not None:
            result.append(cap)
            continue
        if cap.mode == "cli":
            cap = replace(cap, navigation=False, snapshot=False, visual_evidence=())
            try:
                runner.require_cli(cap.route)
            except runner.UnsupportedSelection as error:
                cap = replace(
                    cap,
                    failure=resolver.Failure("unsupported_selection", (*cap.evidence, str(error))),
                )
        elif cap.mode == "native" and cap.route == HARNESS_ROUTES.get(context.actual_harness):
            adapter = _adapter(cap, adapters)
            models = []
            if adapter is not None:
                dynamic = (
                    adapter.model_field,
                    adapter.effort_field,
                    adapter.role_field,
                    adapter.input_field,
                )
                fields_distinct = len(set(dynamic)) == 4 and not set(dynamic).intersection(
                    adapter.fixed
                )
                codex_controls = cap.route != "codex" or (
                    adapter.model_field == "model"
                    and adapter.effort_field == "reasoning_effort"
                    and adapter.role_field == "task_name"
                    and adapter.input_field == "message"
                    and adapter.fixed.get("fork_turns") == "none"
                )
                for model in cap.models:
                    efforts = tuple(
                        e for e in model.efforts if adapter.accepts(adapter.effort_field, e)
                    )
                    fields = [
                        adapter.fields("visual" if r.visual else r.role, model.exact_id, None, line)
                        for r, line in zip(requests, lines, strict=True)
                    ]
                    if (
                        codex_controls
                        and fields_distinct
                        and (not cap.effort_control or adapter.effort_field in adapter.schema)
                        and all(adapter.accepts(k, v) for f in fields for k, v in f.items())
                    ):
                        models.append(replace(model, efforts=efforts))
            if not models:
                cap = replace(
                    cap,
                    failure=resolver.Failure(
                        "unsupported_selection",
                        (*cap.evidence, "actual callable schema lacks native selection controls"),
                    ),
                )
            else:
                cap = replace(cap, models=tuple(models))
        result.append(cap)
    return tuple(result)


def _handoff(outcome: resolver.Unavailable) -> int:
    return fail(
        f"{outcome.operation}: {outcome.constraint}: {outcome.detail}; "
        f"evidence: {', '.join(outcome.evidence) or 'not evidenced'}; "
        + "; ".join(outcome.alternatives),
        3,
    )


def dispatch(
    plan_ref: str | None,
    request: resolver.Request,
    line: str,
    *,
    actual_harness: str,
    capabilities: tuple[resolver.Capability, ...],
    adapters: tuple[NativeAdapter, ...] = (),
    node_id: str | None = None,
    reviewer: resolver.Request | None = None,
    review_line: str | None = None,
    independence: resolver.Independence | None = None,
    review: bool = False,
    completed_execution: resolver.Selection | None = None,
    initial_policy: Policy | None = None,
    record: Callable[[resolver.Selection | resolver.Unavailable], None] | None = None,
) -> int:
    """Supported host entrypoint. Load policy, resolve the current phase, consume its selection.

    Before a plan exists, initial_policy authorizes only a planner Outline with a target,
    without node binding or pair/review options. All later phases require an existing plan.
    No provider discovery, auth or subprocess call occurs until policy and resolution succeed.
    """
    try:
        runner.validate_input(request.role, line)
        if plan_ref is None:
            if initial_policy is None:
                raise ValueError("initial planning requires confirmed initial_policy")
            command, _, target = line.partition(":")
            if request.role != "planner" or request.visual or command != "Outline":
                raise ValueError("without a plan, only planner Outline creation is allowed")
            if not target.split("·", 1)[0].strip():
                raise ValueError("planner Outline requires a nonempty target")
            if node_id is not None or any(
                part.strip().startswith("Node:") for part in line.split("·")
            ):
                raise ValueError("initial planner Outline cannot bind a node; use an existing plan")
            if (
                reviewer is not None
                or review_line is not None
                or independence is not None
                or review
                or completed_execution is not None
            ):
                raise ValueError("initial planner Outline cannot use pair/review options")
        if completed_execution is not None and not review:
            raise ValueError("completed_execution is only valid for review=True")
        if review and (
            request.role != "executor" or reviewer is None or reviewer.role != "verifier"
        ):
            raise ValueError("review requires executor and verifier roles")
        if reviewer is not None:
            if review_line is None:
                raise ValueError("review_line is required for a separate reviewer")
            runner.validate_input(reviewer.role, review_line)
        elif independence is not None and (independence.delivery or independence.quota):
            raise ValueError("independence requires an executor/reviewer pair")
        if plan_ref is None:
            assert initial_policy is not None
            policy = initial_policy
            root = Path.cwd()
            config = load_config(root)
        else:
            if initial_policy is not None:
                raise ValueError("initial_policy cannot override an existing plan")
            plan = load_plan(resolve_plan(plan_ref, Path.cwd()))
            root = plan.root
            config = load_config(plan.root)
            policy = plan_policy(config, plan, actual_harness=actual_harness)
            active_line = review_line if review else line
            assert active_line is not None
            input_node = next(
                (part[6:] for part in active_line.split(" · ") if part.startswith("Node: ")), None
            )
            if input_node is not None and node_id is not None and input_node != node_id:
                raise ValueError("input Node does not match node_id")
            node_id = node_id or input_node
            if request.role == "executor" and node_id is None:
                raise ValueError("executor dispatch requires a node")
            if node_id is not None:
                node = plan.node(node_id)
                expected = {
                    "planner": ("BRIEFING", "REPLAN"),
                    "executor": ("RUNNING",),
                    "verifier": ("VERIFYING",),
                }
                active_role = reviewer.role if review and reviewer is not None else request.role
                if node.status not in expected[active_role]:
                    raise ValueError(
                        f"{node_id} must be set to {'/'.join(expected[active_role])}"
                        " before dispatch"
                    )
                token = {"executor": node.exec_model, "verifier": node.verify_model}.get(
                    request.role
                )
                if token and token != "-":
                    if request.token is not None and request.token != token:
                        raise ValueError(
                            f"{node_id} explicit Graph token {token} cannot be overridden"
                        )
                    request = replace(request, token=token)
                if reviewer is not None:
                    token = node.verify_model
                    if token != "-":
                        if reviewer.token is not None and reviewer.token != token:
                            raise ValueError(
                                f"{node_id} explicit Graph verifier token {token}"
                                " cannot be overridden"
                            )
                        reviewer = replace(reviewer, token=token)
        context = resolver.Context(actual_harness, config.harness)
        # Resolver checks coordinator membership before defaults. Do not inspect tool facts first.
        if policy.harnesses is not None and actual_harness not in policy.harnesses:
            outcome = resolver.resolve(policy, request, context, ())
        elif actual_harness not in HARNESS_ROUTES:
            outcome = resolver.resolve(policy, request, context, ())
        else:
            if review:
                problem = resolver.completed_execution_problem(
                    policy, request, context, completed_execution
                )
                if problem is not None:
                    if record is not None:
                        record(problem)
                    return _handoff(problem)
            requests = (
                (reviewer,) if review else ((request,) if reviewer is None else (request, reviewer))
            )
            lines = (
                (review_line,)
                if review
                else ((line,) if review_line is None else (line, review_line))
            )
            permitted = tuple(
                c
                for c in capabilities
                if c.route in policy.providers
                and (
                    policy.harnesses is None
                    or any(HARNESS_ROUTES[h] == c.route for h in policy.harnesses)
                )
            )
            facts = _capabilities(permitted, adapters, context, requests, lines)
            outcome = (
                resolver.resolve_review(
                    policy, request, reviewer, context, facts, completed_execution, independence
                )
                if review and reviewer is not None
                else resolver.resolve(policy, request, context, facts)
                if reviewer is None
                else resolver.resolve_pair(policy, request, reviewer, context, facts, independence)
            )
        if isinstance(outcome, resolver.Unavailable):
            if record is not None:
                record(outcome)
            return _handoff(outcome)
        selections = outcome if isinstance(outcome, tuple) else (outcome,)
        for selection in selections:
            if record is not None:
                record(selection)
        selection = selections[0]
        if record is None:
            for notice in selection.notices:
                print(f"notice: {notice}", file=sys.stderr)
        input_line = review_line if review else line
        active_request = reviewer if review else request
        assert active_request is not None
        assert input_line is not None
        if selection.mode == "cli":
            code = run_command.run_selection(selection.operation, selection, input_line, str(root))
        else:
            cap = next(
                c
                for c in facts
                if c.delivery_id == selection.delivery_id
                and c.route == selection.route
                and c.mode == "native"
            )
            native = _adapter(cap, adapters)
            assert native is not None
            fields = native.fields(
                "visual" if active_request.visual else selection.operation,
                selection.exact_id,
                selection.effort,
                input_line,
            )
            reply = runner.last_line(native.invoke(fields))
            if not reply or reply.startswith("error:"):
                return fail(f"{selection.operation}: native role failed or gave an empty reply", 3)
            print(reply)
            code = 0
        if code:
            return code
    except (ResolveError, PlanError, ValueError) as error:
        return fail(str(error), 2)
    except OSError as error:
        return fail(str(error), 3)
    return 0


def run(args: argparse.Namespace) -> int:
    records: list[dict[str, object]] = []
    try:
        raw = json.loads(Path(args.facts).read_text(encoding="utf-8"))
        capabilities = []
        for item in raw:
            item = dict(item)
            item["models"] = tuple(
                resolver.Model(
                    **{k: tuple(v) if k in ("aliases", "efforts") else v for k, v in model.items()}
                )
                for model in item["models"]
            )
            for key in ("evidence", "quota_evidence", "visual_evidence"):
                if key in item:
                    item[key] = tuple(item[key])
            if item.get("failure") is not None:
                item["failure"] = resolver.Failure(
                    item["failure"]["reason"], tuple(item["failure"]["evidence"])
                )
            capabilities.append(resolver.Capability(**item))
        code = dispatch(
            args.plan,
            resolver.Request(args.role, args.model, args.allow_low),
            args.line,
            actual_harness=args.actual_harness,
            capabilities=tuple(capabilities),
            node_id=args.node,
            record=lambda result: records.append(asdict(result)),
        )
        if args.record:
            Path(args.record).write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
        return code
    except (ValueError, TypeError, KeyError) as error:
        return fail(f"bad capability facts: {error}", 2)
    except OSError as error:
        return fail(str(error), 3)
