"""Where things are: the project, its config, its data, and the judge's private files."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

DEFAULTS = {
    "data_dir": ".morphogen",
    "trunk": "main",
    "backends": {"default": "files"},
    "sandbox": "auto",  # auto | docker | none
    "sandbox_image": "python:3.12-slim",
    "targets": [],
}


def project_root() -> Path:
    """The project the server works on: explicit env, Claude Code's project dir, or cwd."""
    p = os.environ.get("MORPHOGEN_PROJECT") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return Path(p).resolve()


def load_config(root: Path) -> dict:
    cfg = {k: (v.copy() if isinstance(v, (dict, list)) else v) for k, v in DEFAULTS.items()}
    f = root / "morphogen.yaml"
    if f.exists():
        loaded = yaml.safe_load(f.read_text()) or {}
        for k, v in loaded.items():
            if isinstance(v, dict) and isinstance(cfg.get(k), dict):
                cfg[k] = {**cfg[k], **v}
            else:
                cfg[k] = v
        cfg["_found"] = True
    else:
        cfg["_found"] = False
    return cfg


def data_dir(root: Path, cfg: dict) -> Path:
    d = root / cfg.get("data_dir", ".morphogen")
    d.mkdir(parents=True, exist_ok=True)
    return d


def evidence_path(root: Path, cfg: dict) -> Path:
    """The evidence log lives in git's own directory, not the working tree.

    There it is untracked, so candidate commits cannot sweep it up, it
    survives branch switches, and every worktree of the repository shares it.
    Outside a git repository it falls back to the data directory.
    """
    if cfg.get("evidence_path"):
        return root / cfg["evidence_path"]
    try:
        p = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=root, capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            common = Path(p.stdout.strip())
            common = common if common.is_absolute() else (root / common)
            return common.resolve() / "morphogen" / "evidence.jsonl"
    except OSError:
        pass
    return data_dir(root, cfg) / "evidence.jsonl"


def plugin_root() -> Path:
    """The plugin directory (server/ lives inside it)."""
    return Path(__file__).resolve().parents[2]
