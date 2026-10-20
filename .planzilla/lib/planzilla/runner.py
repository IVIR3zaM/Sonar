"""Pure core of `plz run`: validate the input, build the prompt and argv, pick the reply."""

import json

from planzilla.providers import provider_of, split_token

ROLES = ("planner", "executor", "verifier")
_CLAUDE_TOOLS = {
    "planner": "Read,Grep,Glob,Write,Edit,Bash",
    "executor": "Read,Grep,Glob,Edit,Write,Bash",
    "verifier": "Read,Grep,Glob,Bash",
}
_LOGIN_HINT = {"codex": "codex login", "claude": "claude auth login"}


def validate(role: str, model: str, line: str) -> tuple[str, str, str | None]:
    """Return (cli, name, effort) or raise ValueError with the reason."""
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}: expected {', '.join(ROLES)}")
    name, effort = split_token(model)
    provider = provider_of(name)
    if provider is None:
        raise ValueError(f"model {name!r} has no provider")
    if not line.strip():
        raise ValueError("the input line is empty")
    if "".join(line.splitlines()) != line:
        raise ValueError("the input line holds a line break")
    return provider, name, effort


def build_prompt(role: str, line: str) -> str:
    return (
        f"Follow .planzilla/roles/{role}.md: read it first; it is your whole role.\n"
        f"Input: {line}\n"
        "Reply with exactly the one line that role names, nothing else.\n"
    )


def build_argv(
    role: str, cli: str, name: str, effort: str | None, cwd: str, out_file: str | None
) -> list[str]:
    """The CLI call; codex needs `out_file` for its reply, claude replies on stdout.

    A bare token (`name == cli`) leaves the model flag out: the CLI picks its default model.
    """
    if cli == "codex":
        argv = ["codex", "exec"] + ([] if name == cli else ["-m", name])
        if effort is not None:
            argv += ["-c", f'model_reasoning_effort="{effort}"']
        return argv + [
            "-s",
            "workspace-write",
            "-c",
            "sandbox_workspace_write.network_access=true",
            "-C",
            cwd,
            "-o",
            str(out_file),
            "-",
        ]
    tools = _CLAUDE_TOOLS[role]
    argv = ["claude", "-p"] + ([] if name == cli else ["--model", name])
    if effort is not None:
        argv += ["--effort", effort]
    return argv + [
        "--output-format",
        "text",
        "--no-session-persistence",
        "--tools",
        tools,
        "--allowedTools",
        tools,
        "--permission-mode",
        "dontAsk",
    ]


def login_argv(cli: str) -> list[str]:
    return ["codex", "login", "status"] if cli == "codex" else ["claude", "auth", "status"]


def logged_in(cli: str, code: int, stdout: str) -> bool:
    """codex: exit 0. claude: exit 0 and stdout JSON with `loggedIn` true."""
    if code != 0:
        return False
    if cli == "codex":
        return True
    try:
        data = json.loads(stdout)
    except ValueError:
        return False
    return isinstance(data, dict) and data.get("loggedIn") is True


def login_hint(cli: str) -> str:
    return f"{cli} is not logged in; run {_LOGIN_HINT[cli]}"


def last_line(text: str) -> str:
    """The last non-blank line, stripped; empty when there is none."""
    for line in reversed(text.splitlines()):
        if line.strip():
            return line.strip()
    return ""


def exit_message(cli: str, code: int, stdout: str, stderr: str) -> str:
    detail = last_line(stderr) or last_line(stdout)
    return f"{cli} exited {code}: {detail}" if detail else f"{cli} exited {code}"
