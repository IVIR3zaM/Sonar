"""`.plan/config.md`: `key: value` lines with defaults (FORMAT §8)."""

import re
from dataclasses import dataclass, field
from pathlib import Path

from planzilla.plan import PUSH_ALIASES, PlanError

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
)
RETENTION = ("keep", "prune-logs", "delete", "branch-only")

_LINE_RE = re.compile(r"([a-z_]+):(?: (.*))?")
_MODEL_RE = re.compile(r"[a-z0-9.-]+")


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


def load_config(repo: Path) -> Config:
    """Read `<repo>/.plan/config.md`; a missing file gives all defaults."""
    path = repo / ".plan" / "config.md"
    if not path.is_file():
        return Config()
    return parse_config(path.read_bytes().decode("utf-8"), path)


def parse_config(text: str, file: Path | str) -> Config:
    config = Config()
    seen: set[str] = set()
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
        try:
            _apply(config, key, value)
        except ValueError as error:
            raise PlanError(file, number, f"bad {key} value {value!r}: {error}") from None
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
        for pair in filter(None, (part.strip() for part in value.split(","))):
            role, _, model = pair.partition("=")
            role, model = role.strip(), model.strip()
            if role not in DEFAULT_MODELS or not _MODEL_RE.fullmatch(model):
                raise ValueError("expected 'planner=<m>, exec=<m>, verify=<m>' (any subset)")
            config.models[role] = model


def _choice(value: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ValueError(f"expected one of {', '.join(allowed)}")
    return value
