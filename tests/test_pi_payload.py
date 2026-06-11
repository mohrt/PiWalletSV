"""Pi payload exclude manifest — dev sync and production image must match."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _rsync_payload(dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "rsync",
            "-a",
            "--delete",
            f"--exclude-from={REPO_ROOT / 'scripts' / 'rsync-pi-excludes.txt'}",
            f"{REPO_ROOT}/",
            f"{dest}/",
        ],
        check=True,
    )


def test_pi_payload_excludes_after_rsync(tmp_path: Path) -> None:
    payload = tmp_path / "payload"
    _rsync_payload(payload)
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "verify-pi-payload.sh"), str(payload)],
        check=True,
        cwd=REPO_ROOT,
    )


@pytest.mark.parametrize(
    "forbidden",
    [
        "companion",
        "hardware",
        "docs",
        "tests",
        "releases",
        "site",
        ".pytest_cache",
    ],
)
def test_pi_payload_forbidden_dirs_not_synced(tmp_path: Path, forbidden: str) -> None:
    payload = tmp_path / "payload"
    _rsync_payload(payload)
    assert not (payload / forbidden).exists(), f"{forbidden}/ must not be in Pi payload"


def test_pi_payload_prune_removes_git_clone_bulk(tmp_path: Path) -> None:
    """Simulate git clone (full tree) then prune — production fallback path."""
    payload = tmp_path / "payload"
    shutil.copytree(REPO_ROOT, payload, ignore=shutil.ignore_patterns(".git", ".venv"))
    assert (payload / "docs").is_dir()
    assert (payload / "tests").is_dir()

    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "prune-pi-payload.sh"), str(payload)],
        check=True,
        cwd=REPO_ROOT,
    )
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts" / "verify-pi-payload.sh"), str(payload)],
        check=True,
        cwd=REPO_ROOT,
    )
