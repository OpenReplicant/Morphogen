"""Autonomy policy (decision 0009), read from intent/policies/autonomy.yaml."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

import yaml

_DURATION = re.compile(r"^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$")


def duration(iso: str) -> timedelta:
    m = _DURATION.match(iso)
    if not m:
        raise ValueError(f"unsupported ISO 8601 duration: {iso}")
    d, h, mi, s = (int(x or 0) for x in m.groups())
    return timedelta(days=d, hours=h, minutes=mi, seconds=s)


@dataclass
class Policy:
    matrix: dict[str, dict[str, str]]
    guards: dict
    policies_dir: Path

    @classmethod
    def load(cls, policies_dir: str | Path) -> Policy:
        policies_dir = Path(policies_dir)
        doc = yaml.safe_load((policies_dir / "autonomy.yaml").read_text())
        return cls(matrix=doc["matrix"], guards=doc.get("guards", {}), policies_dir=policies_dir)

    def decide(self, autonomy: str, risk: str) -> str:
        if risk == "irreversible":  # fixed column: always a person
            return "approve"
        return self.matrix[autonomy][risk]

    @property
    def kill_file(self) -> Path:
        name = self.guards.get("kill_switch_file", "policies/KILL")
        return self.policies_dir.parent / name

    def killed(self) -> bool:
        return self.kill_file.exists()

    @property
    def max_per_hour(self) -> int:
        return int(self.guards.get("max_changes_per_hour_per_target", 3))

    @property
    def cooldown(self) -> timedelta:
        return duration(self.guards.get("cooldown_per_slot", "PT0S"))

    @property
    def blast_budget(self) -> int:
        return int(self.guards.get("blast_radius_budget_slots", 5))
