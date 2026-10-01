"""Install the Planzilla kit into a repo."""

import argparse
import os
import re
import shutil
import stat
import sys
import tarfile
import tempfile
import urllib.request
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

ARCHIVE_URL = "https://github.com/IVIR3zaM/Planzilla/archive/refs/tags/{version}.tar.gz"
BEGIN_MARKER = "<!-- planzilla:begin -->"
END_MARKER = "<!-- planzilla:end -->"

LAUNCHER = """#!/usr/bin/env python3
\"\"\"Planzilla launcher: runs the vendored package in .planzilla/lib/.\"\"\"

import os
import sys

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))

from planzilla.cli import main  # noqa: E402

sys.exit(main())
"""

# Kit sub-directory -> install directories (relative to the target).
_KIT_FLAT = {"roles": ".planzilla/roles", "templates": ".planzilla/templates"}
_SKILL_DIRS = (".claude/skills", ".agents/skills")
_AGENT_DIR = ".claude/agents"


class InstallError(Exception):
    """A failure with the exit code it maps to."""

    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.code = code


@dataclass
class Counts:
    added: int = 0
    changed: int = 0
    removed: int = 0


def add_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target", metavar="DIR", help="repo to install into (default: cwd)")
    parser.add_argument(
        "--version",
        metavar="vX",
        help="install this released version (GitHub tag archive) instead of the running package",
    )
    parser.add_argument("--archive-url", metavar="URL", help="download the tag archive from URL")


def read_version(pkg_dir: Path) -> str:
    """`__version__` as written in `<pkg_dir>/__init__.py`."""
    try:
        text = (pkg_dir / "__init__.py").read_text(encoding="utf-8")
    except OSError as exc:
        raise InstallError(f"cannot read version from {pkg_dir}: {exc}", 3) from exc
    match = re.search(r"^__version__\s*=\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)
    if not match:
        raise InstallError(f"no __version__ in {pkg_dir / '__init__.py'}", 3)
    return match.group(1)


def _source_files(root: Path):
    """Yield (posix path relative to root, file path), skipping bytecode caches."""
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if "__pycache__" in rel.parts or path.suffix == ".pyc" or not path.is_file():
            continue
        yield rel.as_posix(), path


def _agents_block(kit: Path) -> str:
    text = (kit / "AGENTS-block.md").read_text(encoding="utf-8")
    return text.rstrip("\n") + "\n"


def desired_files(pkg_dir: Path, version: str) -> dict[str, tuple[bytes, int]]:
    """Every file install writes, except AGENTS.md: relative path -> (bytes, mode)."""
    files: dict[str, tuple[bytes, int]] = {
        ".planzilla/VERSION": (f"{version}\n".encode(), 0o644),
        ".planzilla/plz": (LAUNCHER.encode(), 0o755),
    }
    for rel, path in _source_files(pkg_dir):
        files[f".planzilla/lib/planzilla/{rel}"] = (path.read_bytes(), 0o644)
    kit = pkg_dir / "kit"
    for sub, dest in _KIT_FLAT.items():
        for rel, path in _source_files(kit / sub):
            files[f"{dest}/{rel}"] = (path.read_bytes(), 0o644)
    for rel, path in _source_files(kit / "agents" / "claude"):
        if "/" not in rel and rel.startswith("plz-") and rel.endswith(".md"):
            files[f"{_AGENT_DIR}/{rel}"] = (path.read_bytes(), 0o644)
    for rel, path in _source_files(kit / "skills"):
        if rel.split("/")[0].startswith("plz-"):
            for base in _SKILL_DIRS:
                files[f"{base}/{rel}"] = (path.read_bytes(), 0o644)
    return files


def _owned_roots(target: Path) -> list[Path]:
    """Directories whose contents Planzilla owns: `.planzilla/` and every `plz-*` skill dir."""
    roots = [target / ".planzilla"]
    for base in _SKILL_DIRS:
        skills = target / base
        if skills.is_dir():
            roots += sorted(p for p in skills.iterdir() if p.name.startswith("plz-") and p.is_dir())
    return roots


def _existing_owned(target: Path) -> list[Path]:
    """Existing files and symlinks that the removal pass may touch (D25: only Planzilla's own)."""
    found: list[Path] = []
    agents = target / _AGENT_DIR
    if agents.is_dir():
        found += sorted(
            p
            for p in agents.iterdir()
            if p.name.startswith("plz-") and p.name.endswith(".md") and not p.is_dir()
        )
    for root in _owned_roots(target):
        if root.is_symlink() or not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath)
            found += [here / name for name in filenames]
            found += [here / name for name in dirnames if (here / name).is_symlink()]
    return found


def _prune_empty(target: Path) -> None:
    for root in _owned_roots(target):
        if root.is_symlink() or not root.is_dir():
            continue
        for dirpath, _dirnames, _filenames in os.walk(root, topdown=False):
            here = Path(dirpath)
            if here == target / ".planzilla":
                continue
            if not any(here.iterdir()):
                here.rmdir()


def _write_if_changed(path: Path, data: bytes, mode: int) -> str | None:
    """Write `path` atomically if its bytes (or exec bit) differ; return added/changed/None."""
    if path.is_file() and not path.is_symlink():
        same_bytes = path.read_bytes() == data
        same_exec = (stat.S_IMODE(path.stat().st_mode) & 0o111) == (mode & 0o111)
        if same_bytes and same_exec:
            return None
        outcome = "changed"
    else:
        outcome = "added"
        if path.is_symlink():
            path.unlink()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.plz-tmp")
    tmp.write_bytes(data)
    tmp.chmod(mode)
    os.replace(tmp, path)
    return outcome


def merge_agents_md(existing: str | None, block: str) -> str:
    """AGENTS.md text after install: create, append or replace the marked block."""
    marked = f"{BEGIN_MARKER}\n{block}{END_MARKER}\n"
    if existing is None or existing.strip() == "":
        return marked
    lines = existing.splitlines(keepends=True)
    begins = [i for i, line in enumerate(lines) if line.strip() == BEGIN_MARKER]
    ends = [i for i, line in enumerate(lines) if line.strip() == END_MARKER]
    if not begins and not ends:
        sep = "" if existing.endswith("\n") else "\n"
        return f"{existing}{sep}\n{marked}"
    if len(begins) != 1 or len(ends) != 1 or begins[0] > ends[0]:
        raise InstallError(
            f"AGENTS.md has unpaired {BEGIN_MARKER} / {END_MARKER} markers; fix them first", 2
        )
    begin, end = begins[0], ends[0]
    return "".join(lines[:begin]) + marked + "".join(lines[end + 1 :])


def install_tree(pkg_dir: Path, version: str, target: Path) -> Counts:
    """Vendor the package at `pkg_dir` into `target`; return what changed."""
    files = desired_files(pkg_dir, version)
    agents_path = target / "AGENTS.md"
    old_agents = agents_path.read_text(encoding="utf-8") if agents_path.is_file() else None
    new_agents = merge_agents_md(old_agents, _agents_block(pkg_dir / "kit"))

    counts = Counts()
    for rel, (data, mode) in files.items():
        outcome = _write_if_changed(target / rel, data, mode)
        if outcome == "added":
            counts.added += 1
        elif outcome == "changed":
            counts.changed += 1
    outcome = _write_if_changed(agents_path, new_agents.encode("utf-8"), 0o644)
    if outcome == "added":
        counts.added += 1
    elif outcome == "changed":
        counts.changed += 1

    for path in _existing_owned(target):
        if path.relative_to(target).as_posix() not in files:
            path.unlink()
            counts.removed += 1
    _prune_empty(target)
    return counts


def _safe_extract(archive: Path, dest: Path) -> None:
    root = dest.resolve()
    with tarfile.open(archive) as tar:
        members = tar.getmembers()
        for member in members:
            if not (member.isfile() or member.isdir()):
                raise InstallError(f"unsupported entry in archive: {member.name}", 3)
            if not (root / member.name).resolve().is_relative_to(root):
                raise InstallError(f"unsafe path in archive: {member.name}", 3)
        for member in members:
            member.mode = 0o755 if member.isdir() else 0o644
            tar.extract(member, dest)


def _find_package(tree: Path) -> Path:
    candidates = [tree / "src" / "planzilla", *sorted(tree.glob("*/src/planzilla"))]
    for candidate in candidates:
        if (candidate / "__init__.py").is_file():
            return candidate
    raise InstallError("archive holds no src/planzilla package", 3)


def _download(url: str, tmp: Path) -> Path:
    """Download and extract `url` under `tmp`; return the extracted `src/planzilla` dir."""
    archive = tmp / "archive.tar.gz"
    try:
        with urllib.request.urlopen(url, timeout=60) as response, archive.open("wb") as out:
            shutil.copyfileobj(response, out)
    except (OSError, ValueError) as exc:
        raise InstallError(f"download failed: {url}: {exc}", 3) from exc
    tree = tmp / "tree"
    tree.mkdir()
    try:
        _safe_extract(archive, tree)
    except (tarfile.TarError, OSError, EOFError) as exc:
        raise InstallError(f"cannot extract {url}: {exc}", 3) from exc
    return _find_package(tree)


def run(args: argparse.Namespace) -> int:
    target = Path(args.target) if args.target else Path.cwd()
    try:
        if not target.is_dir():
            raise InstallError(f"target not found: {target}", 2)
        url = args.archive_url or (ARCHIVE_URL.format(version=args.version) if args.version else "")
        if url:
            with tempfile.TemporaryDirectory(prefix="planzilla-install-") as tmp:
                pkg_dir = _download(url, Path(tmp))
                version = read_version(pkg_dir)
                counts = install_tree(pkg_dir, version, target)
        else:
            with resources.as_file(resources.files("planzilla")) as pkg_dir:
                version = read_version(pkg_dir)
                counts = install_tree(pkg_dir, version, target)
    except InstallError as exc:
        print(f"error: {' '.join(str(exc).split())}", file=sys.stderr)
        return exc.code
    except OSError as exc:
        print(f"error: {' '.join(str(exc).split())}", file=sys.stderr)
        return 3
    print(
        f"installed planzilla {version} into {target}: "
        f"{counts.added} added, {counts.changed} changed, {counts.removed} removed"
    )
    return 0
