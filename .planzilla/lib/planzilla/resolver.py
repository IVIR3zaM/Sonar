"""Pure intent resolution over supplied policy and observed capability records (§14).

Records describe enforceable operations, not catalogs or tool discovery. Evidence references
and canonical delivery/quota identities are nonsecret data supplied by the caller. No record
created here establishes live reachability, browser usability or quota separation.
"""

from dataclasses import dataclass

from planzilla.config import Policy
from planzilla.providers import (
    HARNESS_ROUTES,
    PORTABLE_ALIASES,
    PROVIDERS,
    allowed_routes,
    route_of,
    split_token,
)


@dataclass(frozen=True)
class Model:
    exact_id: str
    family: str
    aliases: tuple[str, ...] = ()
    efforts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Failure:
    """An already classified observation on one capability, never a provider-wide ban.

    `unknown` includes generic exit/signal/429/silence without concrete quota semantics.
    Classification of raw process diagnostics belongs to the IO layer.
    """

    reason: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class Capability:
    route: str
    mode: str
    delivery_id: str
    models: tuple[Model, ...]
    model_control: bool
    effort_control: bool
    availability: str
    evidence: tuple[str, ...]
    enabled: bool = True
    default_id: str | None = None
    quota_id: str | None = None
    quota_evidence: tuple[str, ...] = ()
    failure: Failure | None = None
    navigation: bool = False
    snapshot: bool = False
    visual_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class Context:
    actual_harness: str
    configured_harness: str


@dataclass(frozen=True)
class Request:
    role: str
    token: str | None = None
    allow_low: bool = False
    visual: bool = False


@dataclass(frozen=True)
class Independence:
    """Delivery means different routes AND distinct delivery identities.

    Quota requires distinct canonical quota identities, each with separation evidence.
    Both phases always require separate invocations, even when neither flag is set.
    """

    delivery: bool = False
    quota: bool = False


@dataclass(frozen=True)
class Pins:
    exact_id: str | None
    effort: str | None
    route: str | None


@dataclass(frozen=True)
class Selection:
    operation: str
    original: str | None
    intent: str
    family: str
    exact_id: str
    effort: str | None
    actual_harness: str
    route: str
    mode: str
    delivery_id: str
    quota_id: str | None
    quota_evidence: tuple[str, ...]
    evidence: tuple[str, ...]
    visual_evidence: tuple[str, ...]
    pins: Pins
    mismatch: bool
    notices: tuple[str, ...]
    failures: tuple[Failure, ...]
    separate_context: bool = True


@dataclass(frozen=True)
class Unavailable:
    operation: str
    original: str | None
    intent: str | None
    constraint: str
    detail: str
    evidence: tuple[str, ...]
    alternatives: tuple[str, ...]
    mismatch: bool
    failures: tuple[Failure, ...] = ()


def _problem(
    request: Request,
    context: Context,
    intent: str | None,
    constraint: str,
    detail: str,
    evidence: tuple[str, ...] = (),
    failures: tuple[Failure, ...] = (),
) -> Unavailable:
    alternatives = (
        ("restore authentication for this delivery through an authorized recovery step",)
        if constraint == "auth"
        else (
            "supply proven capability evidence or restore this delivery",
            "authorize a constraint change",
        )
    )
    if constraint != "auth" and any(failure.reason == "auth" for failure in failures):
        alternatives += (
            "restore authentication for the failed delivery through authorized recovery",
        )
    return Unavailable(
        request.role,
        request.token,
        intent,
        constraint,
        detail,
        evidence,
        alternatives,
        context.actual_harness != context.configured_harness,
        failures,
    )


def _routes(policy: Policy) -> tuple[str, ...]:
    if policy.harnesses is None:
        return policy.providers
    return tuple(
        p for p in policy.providers if any(HARNESS_ROUTES.get(h) == p for h in policy.harnesses)
    )


def _candidates(
    policy: Policy, request: Request, context: Context, capabilities: tuple[Capability, ...]
) -> tuple[tuple[Selection, ...], Unavailable | None]:
    # D9: coordinator permission precedes defaults, aliases and agent capabilities.
    if policy.harnesses is not None and context.actual_harness not in policy.harnesses:
        return (), _problem(
            request,
            context,
            None,
            "coordinator",
            f"coordinator {context.actual_harness} is not in harnesses",
        )
    if context.actual_harness not in HARNESS_ROUTES:
        return (), _problem(
            request,
            context,
            None,
            "coordinator",
            f"unknown actual harness {context.actual_harness}",
        )
    routes = _routes(policy)
    role = {
        "replan": "planner",
        "replanner": "planner",
        "executor": "exec",
        "verifier": "verify",
    }.get(request.role, request.role)
    intent = request.token if request.token is not None else policy.models.get(role)
    if intent is None or intent == "-":
        return (), _problem(
            request, context, intent, "default", f"no resolved model request for {request.role}"
        )
    try:
        name, effort_pin = split_token(intent)
        token_routes = allowed_routes(intent)
        route_pin = route_of(intent)
    except ValueError as error:
        return (), _problem(request, context, intent, "token", str(error))
    permitted = tuple(route for route in routes if route in token_routes)
    if not permitted:
        return (), _problem(
            request,
            context,
            intent,
            "policy",
            f"{intent} has no delivery permitted by harnesses and providers",
        )
    pins = Pins(
        None if name in PORTABLE_ALIASES or name in PROVIDERS else name, effort_pin, route_pin
    )
    actual_route = HARNESS_ROUTES[context.actual_harness]
    eligible = tuple(cap for cap in capabilities if cap.route in permitted)
    # Stable supplied order breaks ties within a route/mode. Native actual controls win.
    ordered = sorted(
        eligible,
        key=lambda cap: (
            not (cap.mode == "native" and cap.route == actual_route),
            routes.index(cap.route),
        ),
    )
    failures = tuple(cap.failure for cap in ordered if cap.failure is not None)
    notices = (
        (f"configured {context.configured_harness}; actual {context.actual_harness}",)
        if context.actual_harness != context.configured_harness
        else ()
    )
    if any(f.reason == "auth" for f in failures):
        notices += ("restore authentication for the failed delivery through authorized recovery",)
    found: list[Selection] = []
    problems: list[Unavailable] = []
    for cap in ordered:
        selections, problem = _select(
            cap, request, context, intent, name, pins, actual_route, notices, failures
        )
        found.extend(selections)
        if problem is not None:
            problems.append(problem)
    if found:
        return tuple(found), None
    if problems:
        return (), problems[0]
    constraint = "selection" if capabilities else "availability"
    return (), _problem(
        request, context, intent, constraint, f"no proven allowed delivery for {intent}"
    )


def _select(
    cap: Capability,
    request: Request,
    context: Context,
    intent: str,
    name: str,
    pins: Pins,
    actual_route: str,
    notices: tuple[str, ...],
    failures: tuple[Failure, ...],
) -> tuple[tuple[Selection, ...], Unavailable | None]:
    def reject(
        constraint: str, detail: str, evidence: tuple[str, ...] = cap.evidence
    ) -> tuple[tuple[Selection, ...], Unavailable]:
        return (), _problem(request, context, intent, constraint, detail, evidence, failures)

    if cap.failure is not None:
        return reject(
            cap.failure.reason,
            f"{cap.route}/{cap.mode}/{cap.delivery_id}: {cap.failure.reason}",
            cap.failure.evidence,
        )
    expected = "callable_native" if cap.mode == "native" else "external_reply"
    if (
        not cap.enabled
        or not cap.evidence
        or not cap.delivery_id
        or cap.mode not in ("native", "cli")
        or cap.availability != expected
        or (cap.mode == "native" and cap.route != actual_route)
    ):
        return reject("availability", f"{cap.route}/{cap.mode} lacks proven usable delivery")
    if request.visual and not (cap.navigation and cap.snapshot and cap.visual_evidence):
        return reject(
            "visual",
            f"{cap.route}/{cap.mode} lacks proven navigation and snapshot/image operations",
        )
    effort = pins.effort
    if name in PORTABLE_ALIASES:
        if cap.route == "codex":
            models = tuple(model for model in cap.models if model.exact_id == "gpt-6.1-sol")
            effort = effort or {"opus": "high", "sonnet": "medium", "haiku": "low"}[name]
        else:
            models = tuple(model for model in cap.models if name in model.aliases)
    elif name in PROVIDERS:
        models = tuple(model for model in cap.models if model.exact_id == cap.default_id)
        if not models:
            return reject(
                "default", f"{cap.route}/{cap.mode} has no proven exact default resolution"
            )
    else:
        models = tuple(model for model in cap.models if model.exact_id == name)
    if not models:
        return reject(
            "selection", f"{cap.route}/{cap.mode} does not support {intent} with its pins"
        )
    # D1/D2: only the request token's own @low is explicit; mapped or role-default low is gated.
    explicit_low = request.token is not None and pins.effort == "low"
    if effort == "low" and not request.allow_low and not explicit_low:
        return reject("low_effort", f"{intent} needs task policy permitting low effort")
    proven_cli_default = name in PROVIDERS and cap.mode == "cli" and cap.default_id is not None
    if (not cap.model_control and not proven_cli_default) or (
        effort is not None and not cap.effort_control
    ):
        return reject(
            "selection_control",
            f"{cap.route}/{cap.mode} lacks enforceable model/effort selection for {intent}",
        )
    models = tuple(model for model in models if effort is None or effort in model.efforts)
    if not models:
        return reject("selection", f"{cap.route}/{cap.mode} does not support effort {effort}")
    return tuple(
        Selection(
            request.role,
            request.token,
            intent,
            model.family,
            model.exact_id,
            effort,
            context.actual_harness,
            cap.route,
            cap.mode,
            cap.delivery_id,
            cap.quota_id,
            cap.quota_evidence,
            cap.evidence,
            cap.visual_evidence if request.visual else (),
            pins,
            context.actual_harness != context.configured_harness,
            notices,
            failures,
        )
        for model in models
    ), None


def resolve(
    policy: Policy, request: Request, context: Context, capabilities: tuple[Capability, ...]
) -> Selection | Unavailable:
    """Resolve one role. All facts are supplied and inputs are never mutated."""
    candidates, problem = _candidates(policy, request, context, capabilities)
    if candidates:
        return candidates[0]
    assert problem is not None
    return problem


def resolve_pair(
    policy: Policy,
    executor: Request,
    reviewer: Request,
    context: Context,
    capabilities: tuple[Capability, ...],
    independence: Independence | None = None,
) -> tuple[Selection, Selection] | Unavailable:
    """Search the ordered product; fallback cannot collapse deliberate independence."""
    independence = independence or Independence()
    executions, problem = _candidates(policy, executor, context, capabilities)
    if problem is not None:
        return problem
    reviews, problem = _candidates(policy, reviewer, context, capabilities)
    if problem is not None:
        return problem
    return _pair(executor, reviewer, context, executions, reviews, independence)


def completed_execution_problem(
    policy: Policy, executor: Request, context: Context, completed: Selection | None
) -> Unavailable | None:
    """Validate host-attested history against the bound request, without current capabilities."""
    if policy.harnesses is not None and context.actual_harness not in policy.harnesses:
        return _problem(executor, context, None, "coordinator", "coordinator is not in harnesses")
    if context.actual_harness not in HARNESS_ROUTES:
        return _problem(executor, context, None, "coordinator", "unknown actual harness")
    intent = executor.token if executor.token is not None else policy.models.get("exec")
    detail = "completed_execution is required from a successful executor invocation"
    if completed is not None:
        detail = "completed_execution contradicts the bound executor request/pins or lacks evidence"
        try:
            name, effort = split_token(intent or "-")
            pins = Pins(
                None if name in PORTABLE_ALIASES or name in PROVIDERS else name,
                effort,
                route_of(intent or "-"),
            )
            mapped_effort = (
                {"opus": "high", "sonnet": "medium", "haiku": "low"}.get(name)
                if completed.route == "codex"
                else None
            )
            if (
                executor.role in ("executor", "exec")
                and completed.operation == executor.role
                and completed.original == executor.token
                and completed.intent == intent
                and completed.pins == pins
                and (pins.exact_id is None or pins.exact_id == completed.exact_id)
                and (pins.route is None or pins.route == completed.route)
                and (
                    effort is not None or mapped_effort is None or completed.effort == mapped_effort
                )
                and (effort is None or completed.effort == effort)
                and (
                    name not in PORTABLE_ALIASES
                    or completed.route != "codex"
                    or completed.exact_id == "gpt-6.1-sol"
                )
                and (
                    completed.effort != "low"
                    or executor.allow_low
                    or (executor.token is not None and effort == "low")
                )
                and completed.route in allowed_routes(intent or "-")
                and completed.route in HARNESS_ROUTES.values()
                and completed.actual_harness in HARNESS_ROUTES
                and completed.mode in ("native", "cli")
                and completed.delivery_id
                and completed.exact_id
                and completed.evidence
                and completed.separate_context
                and (not executor.visual or completed.visual_evidence)
            ):
                return None
        except ValueError:
            pass
    return _problem(
        executor,
        context,
        intent,
        "completed_execution",
        detail,
        completed.evidence if completed is not None else (),
    )


def resolve_review(
    policy: Policy,
    executor: Request,
    reviewer: Request,
    context: Context,
    capabilities: tuple[Capability, ...],
    completed_execution: Selection | None,
    independence: Independence | None = None,
) -> Selection | Unavailable:
    """Resolve only reviewers against host-retained successful execution history."""
    problem = completed_execution_problem(policy, executor, context, completed_execution)
    if problem is not None:
        return problem
    assert completed_execution is not None
    reviews, problem = _candidates(policy, reviewer, context, capabilities)
    if problem is not None:
        return problem
    pair = _pair(
        executor, reviewer, context, (completed_execution,), reviews, independence or Independence()
    )
    return pair if isinstance(pair, Unavailable) else pair[1]


def _pair(
    executor: Request,
    reviewer: Request,
    context: Context,
    executions: tuple[Selection, ...],
    reviews: tuple[Selection, ...],
    independence: Independence,
) -> tuple[Selection, Selection] | Unavailable:
    delivery_pair = False
    for execution in executions:
        for review in reviews:
            if independence.delivery and (
                execution.route == review.route or execution.delivery_id == review.delivery_id
            ):
                continue
            delivery_pair = True
            if independence.quota and not (
                execution.quota_id is not None
                and review.quota_id is not None
                and execution.quota_id != review.quota_id
                and execution.quota_evidence
                and review.quota_evidence
            ):
                continue
            return execution, review
    constraint = "quota_independence" if delivery_pair else "delivery_independence"
    failures = tuple(
        dict.fromkeys(failure for item in (*executions, *reviews) for failure in item.failures)
    )
    evidence = tuple(
        dict.fromkeys(
            [
                ref
                for item in (*executions, *reviews)
                for ref in (*item.evidence, *item.quota_evidence)
            ]
            + [ref for failure in failures for ref in failure.evidence]
        )
    )
    return _problem(
        Request(f"{executor.role}/{reviewer.role}"),
        context,
        None,
        constraint,
        f"no executor/reviewer pair preserves {constraint}",
        evidence,
        failures,
    )
