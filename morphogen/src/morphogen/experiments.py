"""What the planner, builder, sandbox and actuator agree on about experiments (T6, R5-21).

  experiment_id(request)          the experiment directory a build request gets: intent/experiments/<id>
  run_name(id, role)              the evaluator run of the incumbent or the candidate in it
  provider_dir(provider)          a provider's directory, from its id (Morphogen's modules, then the kernel's)
  provider_slots(provider)        the slots a provider says it fills
  candidate_dir(intent, provider) a candidate's directory in an experiment, from its id
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
EXPERIMENT = re.compile(r"x[0-9a-f]{12}")


def experiment_id(request: str) -> str:
    return "x" + hashlib.sha256(request.encode()).hexdigest()[:12]


def run_name(exp_id: str, role: str) -> str:
    return f"{exp_id}-{role}"


def _meta(d: Path) -> dict:
    f = d / "provider.yaml"
    return (yaml.safe_load(f.read_text()) or {}) if f.exists() else {}


def provider_dir(provider: str) -> Path | None:
    name = provider.removeprefix("urn:kk:provider:")
    if name == provider or not NAME.fullmatch(name):
        return None
    for base in (ROOT / "morphogen" / "modules", ROOT / "kernel" / "providers"):
        if _meta(base / name).get("id") == provider:
            return base / name
    return None


def provider_slots(provider: str) -> list[str]:
    d = provider_dir(provider)
    return list(_meta(d).get("slots") or []) if d else []


def candidate_dir(intent: Path, provider: str) -> Path | None:
    """The one directory under intent/experiments/<id>/ whose provider.yaml has this id."""
    found = [d for exp in sorted((intent / "experiments").glob("x*")) if EXPERIMENT.fullmatch(exp.name)
             for d in sorted(exp.iterdir()) if d.is_dir() and NAME.fullmatch(d.name) and _meta(d).get("id") == provider]
    return found[0] if len(found) == 1 else None
