from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path


def _force_remove(target_dir: Path) -> None:
    """Remove *target_dir*, forcing read-only files (e.g. inside .git) to be deleted."""
    def _on_error(func, path, _exc):
        os.chmod(path, stat.S_IWRITE)
        func(path)

    shutil.rmtree(target_dir, onerror=_on_error)


def clone_repo(repo_url: str, target_dir: Path) -> None:
    """Clone *repo_url* into *target_dir*, then checkout main or master.

    If *target_dir* is non-empty it is deleted first.
    """
    if target_dir.exists() and any(target_dir.iterdir()):
        _force_remove(target_dir)

    subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, str(target_dir)],
        check=True,
        capture_output=True,
        text=True,
    )

    # Determine default branch (main or master)
    result = subprocess.run(
        ["git", "-C", str(target_dir), "rev-parse", "--verify", "main"],
        capture_output=True,
    )
    branch = "main" if result.returncode == 0 else "master"

    subprocess.run(
        ["git", "-C", str(target_dir), "checkout", branch],
        check=True,
        capture_output=True,
        text=True,
    )
