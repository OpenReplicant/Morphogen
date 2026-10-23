"""Sandbox (T6, R5-21): measure an experiment's candidate and the slot's incumbent (measure.py), then
have the evaluator record both run files as DQV measurements (suite sandbox-<slot>), each linked to the
provider it measured.

  python -m sandbox <intent/experiments/<id>>

Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE and, through the PG* environment, create
databases), KK_ROLE (default kkm_sandbox), KK_EVALUATOR_ROLE (default kkm_evaluator), KK_ARTIFACTS.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

from kk.lib import connect, run

from .measure import ROOT, experiment

MODULE = "urn:kk:module:sandbox"


def record(files: list[Path], suite: str) -> str:
    """The evaluator records the run files (a separate agent: the sandbox measures, the evaluator scores)."""
    d = ROOT / "kernel" / "providers" / "evaluator"
    out = subprocess.run([sys.executable, "-m", "evaluator", "--suite", suite, *map(str, files)], cwd=d,
                         capture_output=True, text=True,
                         env={**os.environ, "KK_ROLE": os.environ.get("KK_EVALUATOR_ROLE", "kkm_evaluator"),
                              "PYTHONPATH": os.pathsep.join([str(d), str(ROOT / "kernel" / "src")])})
    if out.returncode:
        raise RuntimeError(f"evaluator: {(out.stderr or out.stdout).strip()[-400:]}")
    return out.stdout


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Measure an experiment's candidate and the incumbent.")
    ap.add_argument("experiment", type=Path)
    a = ap.parse_args(argv)
    exp = a.experiment.resolve()
    slot = yaml.safe_load((exp / "experiment.yaml").read_text())["slot"]
    with connect(os.environ.get("KK_ROLE", "kkm_sandbox")) as conn, conn.cursor() as cur:
        with run(cur, MODULE, {"experiment": exp.name, "slot": slot}) as (_, outputs):
            files = experiment(exp, conn)
            results = {f.stem: json.loads(f.read_text()) for f in files}
            outputs.update(runs={k: {"contract": v["contract"], "metric": v["metric"]} for k, v in results.items()})
            print(record(files, f"sandbox-{slot}"), end="")
    print(json.dumps(outputs["runs"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
