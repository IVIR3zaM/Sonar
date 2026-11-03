"""Pure model-token grammar and delivery-policy checks (not capability discovery)."""

import re
from collections.abc import Sequence

PROVIDERS = ("claude", "codex", "copilot")
_EFFORTS = {
    "claude": ("low", "medium", "high", "max"),
    "codex": ("low", "medium", "high", "xhigh", "max"),
    "copilot": ("none", "minimal", "low", "medium", "high", "xhigh", "max"),
}
PORTABLE_ALIASES = ("opus", "sonnet", "haiku")
MODEL_ROLES = ("planner", "exec", "verify")
_CLAUDE_NAMES = ("opus", "sonnet", "haiku", "fable")
HARNESSES = ("claude-code", "codex", "copilot")
HARNESS_ROUTES = {"claude-code": "claude", "codex": "codex", "copilot": "copilot"}
# Harness facts (FORMAT §14): models run natively (no `@<effort>`); has a visual agent.
_NATIVE = {"claude-code": _CLAUDE_NAMES, "codex": (), "copilot": ()}
_VISUAL_AGENT = {"claude-code": True, "codex": False, "copilot": False}
_TOKEN_RE = re.compile(r"(?:([a-z0-9.-]+)::)?([a-z0-9.-]+)(?:@([a-z]+))?")


def provider_of(name: str) -> str | None:
    """Legacy name/family classifier; this never establishes a delivery or quota identity."""
    if name in PROVIDERS:
        return name
    if name in _CLAUDE_NAMES or name.startswith("claude-"):
        return "claude"
    if name.startswith("gpt-"):
        return "codex"
    return None


def efforts_of(provider: str) -> tuple[str, ...]:
    return _EFFORTS[provider]


def split_token(token: str) -> tuple[str, str | None]:
    """Validate `[route::]name[@effort]`, returning the name and effort without the route."""
    match = _TOKEN_RE.fullmatch(token)
    if not match:
        raise ValueError(f"bad model token {token!r}: expected [<route>::]<name>[@<effort>]")
    route, name, effort = match.groups()
    if route is not None:
        if route not in PROVIDERS:
            raise ValueError(f"bad model token {token!r}: unknown route {route}")
        if name == "-" or route not in _routes_for_name(name):
            raise ValueError(
                f"bad model token {token!r}: {name} is incompatible with route {route}"
            )
    if effort is not None:
        provider = provider_of(name)
        if provider is None:
            raise ValueError(f"bad model token {token!r}: {name} takes no effort")
        if effort not in _EFFORTS[provider]:
            levels = ", ".join(_EFFORTS[provider])
            raise ValueError(f"bad model token {token!r}: {provider} efforts are {levels}")
    return name, effort


def _routes_for_name(name: str) -> tuple[str, ...]:
    """Syntactically compatible routes; membership is no evidence of model availability."""
    if name in PROVIDERS:
        return (name,)
    if name in PORTABLE_ALIASES:
        return PROVIDERS
    family = provider_of(name)
    if family == "claude":
        return ("claude", "copilot")
    if family == "codex":
        return ("codex", "copilot")
    return PROVIDERS


def route_of(token: str) -> str | None:
    """Only an explicit qualifier or bare CLI default fixes delivery; prefixes do not."""
    name, _ = split_token(token)
    return token.split("::", 1)[0] if "::" in token else name if name in PROVIDERS else None


def allowed_routes(token: str) -> tuple[str, ...]:
    """The token's route constraints, without selecting a route or claiming reachability."""
    name, _ = split_token(token)
    route = route_of(token)
    return (route,) if route is not None else _routes_for_name(name)


def check_allowed(token: str, providers: Sequence[str]) -> None:
    """Reject a disabled explicit route or a model incompatible with all allowed routes."""
    routes = allowed_routes(token)
    if token != "-" and not any(route in providers for route in routes):
        required = routes[0] if len(routes) == 1 else f"one of {', '.join(routes)}"
        raise ValueError(f"provider {required} is not in providers")


def parse_providers(value: str) -> tuple[str, ...]:
    names = tuple(part.strip() for part in value.split(","))
    if not value or any(name not in PROVIDERS for name in names) or len(set(names)) < len(names):
        raise ValueError(f"expected a comma-separated subset of {', '.join(PROVIDERS)}, no repeats")
    return names


def parse_harnesses(value: str) -> tuple[str, ...]:
    names = tuple(part.strip() for part in value.split(","))
    if any(name not in HARNESSES for name in names) or len(set(names)) < len(names):
        raise ValueError(f"expected a comma-separated subset of {', '.join(HARNESSES)}, no repeats")
    return names


def parse_models(value: str) -> dict[str, str]:
    models: dict[str, str] = {}
    for pair in value.split(","):
        role, separator, model = pair.strip().partition("=")
        role, model = role.strip(), model.strip()
        if not separator or role not in MODEL_ROLES:
            raise ValueError("expected 'planner=<m>, exec=<m>, verify=<m>' (any nonempty subset)")
        if role in models:
            raise ValueError(f"repeated model role: {role}")
        if model == "-":
            raise ValueError("role default cannot be '-'")
        models[role] = check_token(model)
    return models


def check_token(token: str) -> str:
    """The one token check: return the token unchanged or raise ValueError."""
    split_token(token)
    return token


def runs_natively(harness: str, token: str) -> bool:
    """True when the harness dispatches the model token with its own agents (no `plz run`)."""
    return token in _NATIVE[harness]


def has_visual_agent(harness: str) -> bool:
    return _VISUAL_AGENT[harness]
