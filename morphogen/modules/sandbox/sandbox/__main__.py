"""Sandbox (T6, R5-21): measure an experiment's candidate and the slot's incumbent (measure.py), then
have the evaluator record both run files as DQV measurements (suite sandbox-<slot>), each linked to the
provider it measured.

  python -m sandbox <intent/experiments/<id>>     one experiment
  python -m sandbox                               a service: each candidate the builder records, once

As a service it follows the change feed for candidates (`<candidate> dcterms:source <request>`, by the
builder) and measures the experiment each one's reference names, under KK_INTENT_DIR; an experiment it
has run before (its runs, by experiment) is not run again.
Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE and, through the PG* environment, create
databases), KK_ROLE (default kkm_sandbox), KK_EVALUATOR_ROLE (default kkm_evaluator), KK_ARTIFACTS,
KK_INTENT_DIR (default morphogen/intent), KK_BUILDER_AGENTS (default urn:kk:agent:builder).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

import yaml

from kk.lib import connect, follow, run

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


def one(conn, exp: Path) -> dict:
    slot = yaml.safe_load((exp / "experiment.yaml").read_text())["slot"]
    with conn.cursor() as cur, run(cur, MODULE, {"experiment": exp.name, "slot": slot}) as (_, outputs):
        files = experiment(exp, conn)
        results = {f.stem: json.loads(f.read_text()) for f in files}
        outputs.update(runs={k: {"contract": v["contract"], "metric": v["metric"]} for k, v in results.items()})
        print(record(files, f"sandbox-{slot}"), end="", flush=True)
    return outputs["runs"]


CANDIDATE_REF = re.compile(r"^file:(?:.*/)?experiments/(x[0-9a-f]{12})/[a-z0-9-]+#sha256=[0-9a-f]{64}$")


def pending(conn, builders: list[str]) -> list[str]:
    """Experiments the builder recorded a candidate for and this module has not run."""
    rows = conn.execute("""select r.source_uri from api.claims c join api.claim_references r on r.claim_id = c.id
                           where c.predicate = 'http://purl.org/dc/terms/source' and c.object_entity like 'urn:kk:request:%%'
                             and c.attributed_to = any(%s) and c.status <> 'deprecated'""", (builders,)).fetchall()
    done = {r[0] for r in conn.execute("select info->>'experiment' from kernel.run where module = %s", (MODULE,)).fetchall()}
    found = [m.group(1) for (uri,) in rows if (m := CANDIDATE_REF.match(uri or ""))]
    return sorted(set(found) - done)


def serve(conn, intent: Path, builders: list[str]) -> None:
    def step(c):
        for exp_id in pending(c, builders):
            exp = intent / "experiments" / exp_id
            try:
                print(json.dumps({exp_id: one(c, exp)}), flush=True)
            except Exception as e:               # a failed run, recorded; the next candidate still runs
                print(json.dumps({exp_id: {"error": str(e)[:300]}}), flush=True)
    follow(conn, step, wake=lambda e: "http://purl.org/dc/terms/source" in (e["predicates"] or []))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Measure an experiment's candidate and the incumbent.")
    ap.add_argument("experiment", type=Path, nargs="?")
    a = ap.parse_args(argv)
    conn = connect(os.environ.get("KK_ROLE", "kkm_sandbox"))
    if a.experiment:
        print(json.dumps(one(conn, a.experiment.resolve())))
        return 0
    intent = Path(os.environ.get("KK_INTENT_DIR", ROOT / "morphogen" / "intent")).resolve()
    builders = [x.strip() for x in os.environ.get("KK_BUILDER_AGENTS", "urn:kk:agent:builder").split(",") if x.strip()]
    serve(conn, intent, builders)
    return 0


if __name__ == "__main__":
    sys.exit(main())
