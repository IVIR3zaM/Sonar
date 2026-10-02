"""run.sh loads .env, syncs the allowed emails and starts Sonar (a fake `uv` records the calls)."""

import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FAKE_UV = """#!/usr/bin/env bash
echo "$* | db=${SONAR_DB_PATH-}" >> "$UV_LOG"
if [ "${FAKE_UV_FAIL_SYNC-}" = 1 ] && [ "${3-}" = sync-emails ]; then exit 1; fi
"""


def run_script(tmp_path: Path, env_file: str | None, fail_sync: bool = False):
    shutil.copy(ROOT / "run.sh", tmp_path / "run.sh")
    if env_file is not None:
        (tmp_path / ".env").write_text(env_file)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake_uv = bin_dir / "uv"
    fake_uv.write_text(FAKE_UV)
    fake_uv.chmod(0o755)
    log = tmp_path / "uv.log"
    env = {
        "PATH": f"{bin_dir}:/usr/bin:/bin",
        "HOME": str(tmp_path),
        "UV_LOG": str(log),
    }
    if fail_sync:
        env["FAKE_UV_FAIL_SYNC"] = "1"
    result = subprocess.run(
        ["bash", "run.sh"], cwd=tmp_path, env=env, capture_output=True, text=True
    )
    calls = log.read_text().splitlines() if log.exists() else []
    return result, calls


def test_without_env_file_it_exits_and_names_the_example(tmp_path):
    result, calls = run_script(tmp_path, None)

    assert result.returncode == 1
    assert ".env.example" in result.stderr
    assert calls == []


def test_allowed_emails_are_split_trimmed_and_synced_before_start(tmp_path):
    env_file = (
        'SONAR_DB_PATH=/tmp/x/sonar.db\nSONAR_ALLOWED_EMAILS=" a@example.com, b@example.com "\n'
    )

    result, calls = run_script(tmp_path, env_file)

    assert result.returncode == 0
    assert calls == [
        "run sonar sync-emails a@example.com b@example.com | db=/tmp/x/sonar.db",
        "run sonar | db=/tmp/x/sonar.db",
    ]


def test_empty_allowed_emails_leaves_the_access_list_alone(tmp_path):
    result, calls = run_script(tmp_path, "SONAR_DB_PATH=/tmp/x/sonar.db\nSONAR_ALLOWED_EMAILS=\n")

    assert result.returncode == 0
    assert calls == ["run sonar | db=/tmp/x/sonar.db"]


def test_failing_sync_stops_before_the_server_starts(tmp_path):
    result, calls = run_script(tmp_path, "SONAR_ALLOWED_EMAILS=a@example.com\n", fail_sync=True)

    assert result.returncode != 0
    assert calls == ["run sonar sync-emails a@example.com | db="]


def test_copied_example_only_starts_sonar(tmp_path):
    example = (ROOT / ".env.example").read_text()

    result, calls = run_script(tmp_path, example)

    assert result.returncode == 0
    assert calls == ["run sonar | db=data/sonar.db"]
