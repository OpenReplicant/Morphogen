"""Prometheus observer: scrapes each target's metrics endpoint at every window boundary and records each
configured histogram's mean over the window as an observation of the target (observe.py).

  python -m observer_prometheus

KK_PROM_TARGETS names the targets: `<subject>=<url>` pairs, comma-separated (the subject is the node the
system encoder recorded, e.g. urn:kk:node:podinfo:frontend=http://127.0.0.1:9898/metrics). Each window
(KK_WINDOW_SECONDS, default 60, aligned to the clock) gives one change set, keyed by the window end, so a
restart never records a window twice. A target that cannot be scraped gives no observation for the
windows on either side of the failure, and the error is printed.
Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_observer_prometheus),
KK_PROM_TARGETS, KK_WINDOW_SECONDS, KK_SCRAPE_TIMEOUT (seconds, default 5), KK_SCRAPE_MAX_BYTES (default 4 MB).
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import urllib.request
from pathlib import Path

import yaml

from kk.lib import connect, run, submit

from .observe import ops, totals

MODULE = "urn:kk:module:observer-prometheus"
AGENT = "urn:kk:agent:observer-prometheus"
SCOPE = "urn:kk:scope:default"
CONFIG = Path(__file__).resolve().parents[1] / "metrics.yaml"


def targets(spec: str) -> dict[str, str]:
    out = {}
    for part in filter(None, (x.strip() for x in spec.split(","))):
        subject, _, url = part.partition("=")
        if not subject.startswith("urn:") or not url.startswith(("http://", "https://")):
            raise ValueError(f"KK_PROM_TARGETS: {part!r} is not <subject>=<http url>")
        out[subject] = url
    return out


def scrape(url: str, config: dict, timeout: float, max_bytes: int) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return totals(r.read(max_bytes).decode("utf-8", "replace"), config)


def record(conn, found: list[dict], end: float) -> dict:
    if not found:
        return {"window_end": end, "observations": 0}
    cs = {"idempotency_key": f"observer-prometheus|{end:.0f}", "attributed_to": AGENT, "target_scope": SCOPE, "ops": found}
    with conn.cursor() as cur, run(cur, MODULE, {"window_end": end}) as (run_id, outputs):
        res = submit(cur, cs, run_id)
        outputs.update(observations=len(found))
    return {"window_end": end, "observations": len(found), "change_set": str(res["id"]), "status": res["status"]}


def main() -> int:
    seconds = float(os.environ.get("KK_WINDOW_SECONDS", "60"))
    timeout = float(os.environ.get("KK_SCRAPE_TIMEOUT", "5"))
    max_bytes = int(os.environ.get("KK_SCRAPE_MAX_BYTES", str(4 << 20)))
    want = targets(os.environ.get("KK_PROM_TARGETS", ""))
    if not want:
        print("observer-prometheus: KK_PROM_TARGETS names no target", file=sys.stderr)
        return 2
    config = yaml.safe_load(CONFIG.read_text())
    conn = connect(os.environ.get("KK_ROLE", "kkm_observer_prometheus"))
    print(json.dumps({"targets": want, "window_seconds": seconds}), flush=True)
    last: dict[str, dict | None] = {}
    while True:
        end = math.floor(time.time() / seconds) * seconds + seconds
        time.sleep(max(0.0, end - time.time()))
        found = []
        for subject, url in want.items():
            try:
                now = scrape(url, config, timeout, max_bytes)
            except Exception as e:
                print(json.dumps({"target": subject, "error": str(e)[:200]}), file=sys.stderr, flush=True)
                now = None
            if last.get(subject) is not None and now is not None:
                found += ops(subject, url, last[subject], now, end - seconds, end, config)
            last[subject] = now
        try:
            print(json.dumps(record(conn, found, end)), flush=True)
        except Exception as e:               # the record is unreachable: say so; the next window tries again
            print(json.dumps({"error": str(e)[:300]}), file=sys.stderr, flush=True)


if __name__ == "__main__":
    sys.exit(main())
