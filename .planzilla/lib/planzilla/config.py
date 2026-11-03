"""`.plan/config.md`: `key: value` lines with defaults (FORMAT §8)."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from planzilla.plan import PUSH_ALIASES, Header, Plan, PlanError
from planzilla.providers import (
    HARNESS_ROUTES,
    HARNESSES,
    check_allowed,
    parse_models,
    parse_providers,
)

DEFAULT_MODELS = {"planner": "opus", "exec": "sonnet", "verify": "sonnet"}
KEYS = (
    "verify",
    "verify_fast",
    "commit",
    "push",
    "retention",
    "visual_recipe",
    "models",
    "preauthorized",
    "always_review",
    "commit_trailer",
    "providers",
    "harness",
)
RETENTION = ("keep", "prune-logs", "delete", "branch-only")

_LINE_RE = re.compile(r"([a-z_]+):(?: (.*))?")


@dataclass
class Config:
    verify: str = ""
    verify_fast: str = ""
    commit: str = "per-node"
    push: str = "none"
    retention: str = "keep"
    visual_recipe: str = ""
    models: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MODELS))
    preauthorized: list[str] = field(default_factory=list)
    always_review: bool = False
    commit_trailer: str = ""
    providers: tuple[str, ...] = ("claude",)
    harness: str = "claude-code"


@dataclass(frozen=True)
class Policy:
    providers: tuple[str, ...]
    models: dict[str, str]
    harnesses: tuple[str, ...] | None = None


def effective_policy(
    config: Config, header: Header, file: Path | str, *, actual_harness: str | None = None
) -> Policy:
    """Compose supplied data only: plan routes replace, plan roles override individually."""
    if (
        header.harnesses is not None
        and actual_harness is not None
        and actual_harness not in header.harnesses
    ):
        raise PlanError(
            file,
            header.lines.get("harnesses", 1),
            f"coordinator {actual_harness} is not in harnesses",
        )
    providers = config.providers if header.providers is None else header.providers
    original = providers
    if header.harnesses is not None:
        routes = tuple(HARNESS_ROUTES[h] for h in header.harnesses)
        providers = tuple(p for p in providers if p in routes)
        if not providers:
            raise PlanError(
                file,
                header.lines.get("harnesses", 1),
                "harnesses and providers have no allowed delivery",
            )
    models = {**config.models, **header.models}
    for role, model in models.items():
        try:
            check_allowed(model, providers)
        except ValueError as error:
            key = "models" if role in header.models else "providers"
            if role not in header.models and providers != original:
                key = "harnesses"
            number = header.lines.get(key, 1)
            raise PlanError(file, number, f"bad models value {model!r}: {error}") from None
    return Policy(providers, models, header.harnesses)


def plan_policy(config: Config, plan: Plan, *, actual_harness: str | None = None) -> Policy:
    """Validate effective defaults and explicit plan restrictions before action or mutation.

    Omitted policy keeps legacy Graph editing behavior; dispatch always resolves its request.
    """
    policy = effective_policy(config, plan.header, plan.graph_file, actual_harness=actual_harness)
    if plan.header.providers is not None or plan.header.harnesses is not None or plan.header.models:
        for node in plan.nodes:
            for token in (node.exec_model, node.verify_model):
                try:
                    check_allowed(token, policy.providers)
                except ValueError as error:
                    raise PlanError(
                        plan.graph_file, node.line or 1, f"{node.id} model {token}: {error}"
                    ) from None
    return policy


def parse_config(text: str, file: Path | str) -> Config:
    config = Config()
    seen: set[str] = set()
    lines: dict[str, int] = {}
    for number, line in enumerate(text.split("\n"), 1):
        if not line.strip() or line.startswith("#"):
            continue
        match = _LINE_RE.fullmatch(line)
        if not match:
            raise PlanError(file, number, f"expected 'key: value', got {line!r}")
        key, value = match.group(1), (match.group(2) or "").strip()
        if key not in KEYS:
            raise PlanError(file, number, f"unknown config key: {key}")
        if key in seen:
            raise PlanError(file, number, f"repeated config key: {key}")
        seen.add(key)
        lines[key] = number
        try:
            _apply(config, key, value)
        except ValueError as error:
            raise PlanError(file, number, f"bad {key} value {value!r}: {error}") from None
    if "models" in seen:
        _check_listed(config, lines["models"], file)
    if "verify_fast" not in seen:
        config.verify_fast = config.verify
    return config


def _apply(config: Config, key: str, value: str) -> None:
    if key in ("verify", "verify_fast", "visual_recipe"):
        setattr(config, key, value)
    elif key == "commit":
        config.commit = _choice(value, ("per-node", "none"))
    elif key == "push":
        config.push = PUSH_ALIASES[_choice(value, tuple(PUSH_ALIASES))]
    elif key == "retention":
        config.retention = _choice(value, RETENTION)
    elif key == "always_review":
        config.always_review = _choice(value, ("yes", "no")) == "yes"
    elif key == "preauthorized":
        config.preauthorized = [item.strip() for item in value.split(";") if item.strip()]
    elif key == "commit_trailer":
        config.commit_trailer = value.replace("\\n", "\n")
    elif key == "models":
        config.models.update(parse_models(value))
    elif key == "harness":
        config.harness = _choice(value, HARNESSES)
    elif key == "providers":
        config.providers = parse_providers(value)


def _choice(value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ValueError(f"expected one of {', '.join(allowed)}")
    return value


def _check_listed(config: Config, number: int, file: Path | str) -> None:
    """Check route constraints after every field has been parsed (either line order)."""
    for model in config.models.values():
        try:
            check_allowed(model, config.providers)
        except ValueError as error:
            raise PlanError(file, number, f"bad models value {model!r}: {error}") from None
