"""Morphogen's policies (intent/policies/): the fixed action list and the lane for a plan (R5-08, R5-20).

  route(policy, level, risk) -> "auto" | "review"
  actions(intent)            -> the action list (actions.yaml)

The lane a planner asks for comes from the autonomy matrix: report and approve mean review; auto and
auto_notify mean auto. Irreversible changes always need a person. The store has the last word: it forces
review for plan steps (review_types, lane-autonomy's migration), so a lane can be raised here, never lowered.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REVIEW = {"report", "approve"}
AUTO = {"auto", "auto_notify"}


def load(intent: Path, name: str) -> dict:
    return yaml.safe_load((Path(intent) / "policies" / name).read_text())


def autonomy(intent: Path) -> dict:
    return load(intent, "autonomy.yaml")


def actions(intent: Path) -> dict:
    return load(intent, "actions.yaml")["actions"]


def level(policy: dict, module: str) -> str:
    levels = policy.get("levels", {})
    return levels.get(module, levels.get("default", "L0"))


def route(policy: dict, level: str, risk: str) -> str:
    if risk == "irreversible":
        return "review"
    decision = policy["matrix"].get(level, {}).get(risk)
    if decision in AUTO:
        return "auto"
    if decision in REVIEW:
        return "review"
    raise ValueError(f"no lane for level {level!r} and risk {risk!r}")
