"""Command dispatcher: every command lives in `planzilla/commands/<name>.py`."""

import argparse
import importlib
import sys
from collections.abc import Sequence

from planzilla import __version__

COMMANDS = [
    "install",
    "next",
    "set",
    "resume",
    "brief",
    "log",
    "check",
    "commit",
    "status",
    "stats",
    "lint",
    "serve",
]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="planzilla")
    parser.add_argument("--version", action="version", version=f"planzilla {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="<command>", required=True)
    for name in COMMANDS:
        module = importlib.import_module(f"planzilla.commands.{name}")
        doc = (module.__doc__ or "").strip()
        command = sub.add_parser(name, help=doc, description=doc)
        module.add_arguments(command)
        command.set_defaults(_module=module)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args._module.run(args)


if __name__ == "__main__":
    sys.exit(main())
