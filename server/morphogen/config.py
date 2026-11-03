"""Where things are: the project, its config, its data, and the judge's private files."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import documents


def project_root() -> Path:
    """The project the server works on: explicit env, Claude Code's project dir, or cwd."""
    p = os.environ.get("MORPHOGEN_PROJECT") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return Path(p).resolve()


def load_config(root: Path) -> dict:
    """morphogen.yaml, checked against its schema (documents.Config), with defaults filled in."""
    f = root / "morphogen.yaml"
    cfg = documents.load("config", f) if f.exists() else documents.validate("config", {})
    cfg["_found"] = f.exists()
    return cfg


def data_dir(root: Path, cfg: dict) -> Path:
    d = root / cfg.get("data_dir", ".morphogen")
    d.mkdir(parents=True, exist_ok=True)
    return d


def store_dir(root: Path, cfg: dict) -> Path:
    """Where the SQLite database (lists and logs) lives: in git's own directory, not the working tree.

    There it is untracked, so candidate commits cannot sweep it up, it survives
    branch switches, and every worktree of the repository shares it. Outside a
    git repository it falls back to the data directory.
    """
    try:
        p = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=root, capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            common = Path(p.stdout.strip())
            common = common if common.is_absolute() else (root / common)
            return common.resolve() / "morphogen"
    except OSError:
        pass
    return data_dir(root, cfg)


def sqlite_path(root: Path, cfg: dict) -> Path:
    """backends.sqlite.path if set (relative to the project), else morphogen.db in store_dir."""
    explicit = ((cfg.get("backends") or {}).get("sqlite") or {}).get("path")
    p = (root / explicit) if explicit else store_dir(root, cfg) / "morphogen.db"
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def plugin_root() -> Path:
    """The plugin directory (server/ lives inside it)."""
    return Path(__file__).resolve().parents[2]
