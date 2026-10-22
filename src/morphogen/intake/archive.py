"""Raw event archive: append-only JSONL, one file per UTC day.

The default provider for the archive slot; swap for an object store exporter.
"""

from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path


class Archive:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def path(self, channel: str, day: datetime | None = None) -> Path:
        day = day or datetime.now(UTC)
        return self.root / channel / f"{day:%Y-%m-%d}.jsonl"

    def append(self, channel: str, event: dict) -> None:
        p = self.path(channel)
        with self._lock:
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a") as f:
                f.write(json.dumps(event, separators=(",", ":"), default=str) + "\n")

    def read(self, channel: str) -> list[dict]:
        out = []
        for p in sorted((self.root / channel).glob("*.jsonl")):
            out += [json.loads(line) for line in p.read_text().splitlines() if line]
        return out
