"""Where things are: the project, its config, its data, and the judge's private files."""

from __future__ import annotations

import hashlib
import os
import secrets
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


def private_dir(root: Path) -> Path:
    """Judge-only files (secret seeds), kept outside the project."""
    base = Path(os.environ.get("MORPHOGEN_PRIVATE") or Path.home() / ".local" / "share" / "morphogen")
    d = base / hashlib.sha256(str(root).encode()).hexdigest()[:16]
    d.mkdir(parents=True, exist_ok=True)
    return d


def judge_secret(root: Path) -> bytes:
    f = private_dir(root) / "secret"
    if not f.exists():
        f.write_text(secrets.token_hex(32))
        f.chmod(0o600)
    return bytes.fromhex(f.read_text().strip())


def plugin_root() -> Path:
    """The plugin directory (server/ lives inside it)."""
    return Path(__file__).resolve().parents[2]
