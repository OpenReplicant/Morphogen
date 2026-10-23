"""Builder (T6, R5-21): whenever the change feed carries a build request (and every KK_SWEEP_SECONDS) it
builds a candidate for each request it has not tried (build.py), commits the experiment to intent
(message `request:<iri> experiment:<id>`), and records the candidate: `<candidate> rdfs:label` and
`<candidate> dcterms:source <request>`, deterministic, referenced by the experiment directory and the
candidate's content hash. A request is tried once: a failed build is a failed run, and a new request
(from a new anomaly) is needed to try again.

  python -m builder [--once]

Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_builder), KK_INTENT_DIR
(default morphogen/intent; experiments go to its experiments/), KK_BUILDER_STRATEGY (fixture | harness),
KK_BUILDER_FIXTURES (for fixture), KK_BUILDER_COMMAND (for harness), KK_SWEEP_SECONDS.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from kk.lib import connect, follow, run, submit

from .build import ROOT, build, incumbent_dir

MODULE = "urn:kk:module:builder"
AGENT = "urn:kk:agent:builder"
SCOPE = "urn:kk:scope:default"
DCT = "http://purl.org/dc/terms/"
OA = "http://www.w3.org/ns/oa#"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
BUILD = "urn:kk:action:build-candidate"
COMMITTER = {"GIT_AUTHOR_NAME": "Morphogen builder", "GIT_AUTHOR_EMAIL": "builder@morphogen.invalid",
             "GIT_COMMITTER_NAME": "Morphogen builder", "GIT_COMMITTER_EMAIL": "builder@morphogen.invalid"}


def requests(cur) -> list[dict]:
    cur.execute("""select subject, predicate, object_entity, object_value->>'@value', id from api.claims
                   where subject in (select subject from api.claims where predicate = %s and object_entity = %s
                                     and status <> 'deprecated')
                     and status <> 'deprecated'""", (DCT + "type", BUILD))
    out: dict[str, dict] = {}
    for s, p, oe, ov, cid in cur.fetchall():
        r = out.setdefault(s, {"iri": s, "claims": []})
        r["claims"].append(str(cid))
        if p == OA + "hasTarget":
            r["target"] = oe
        elif p == DCT + "subject":
            r["slot"] = oe
        elif p == OA + "bodyValue":
            r["text"] = ov
    return [r for r in out.values() if r.get("target") and r.get("slot") and r.get("text")]


def commit(intent: Path, exp: Path, msg: str) -> str:
    git = lambda *a: subprocess.run(["git", "-C", str(intent), *a], check=True, capture_output=True, text=True,
                                    env={**os.environ, **COMMITTER}).stdout.strip()
    rel = str(exp.relative_to(intent))
    git("add", "--", rel)
    git("commit", "-q", "-m", msg, "--", rel)
    return git("rev-parse", "HEAD")


def one_pass(conn, intent: Path, strategy: str, fixtures: Path | None, command: str | None) -> dict:
    report = {}
    with conn.cursor() as cur:
        cur.execute("select distinct info->>'request' from kernel.run where agent = %s and info ? 'request'", (AGENT,))
        tried = {r[0] for r in cur.fetchall()}
        for r in requests(cur):
            if r["iri"] in tried:
                continue
            slot = r["slot"].removeprefix("urn:kk:slot:")
            try:
                with run(cur, MODULE, {"request": r["iri"], "slot": slot, "strategy": strategy}, used=r["claims"]) as (run_id, outputs):
                    inc = incumbent_dir(r["target"])
                    if inc is None:
                        raise ValueError(f"no provider directory for {r['target']}")
                    got = build(r, slot, inc, intent / "experiments", strategy, fixtures, command)
                    sha = commit(intent, got["dir"], f"request:{r['iri']} experiment:{got['id']}\n\nCandidate {got['provider']} "
                                                     f"for the {slot} slot ({strategy}).\n")
                    rel = got["dir"].relative_to(intent.parent) if got["dir"].is_relative_to(intent.parent) else got["dir"]
                    ref = [{"source_uri": f"file:{rel}/{got['candidate']}#sha256={got['sha256']}"}]
                    claim = lambda p, o: {"op": "add_claim", "subject": got["provider"], "predicate": p, "object": o,
                                          "evidence_type": "deterministic", "references": ref}
                    res = submit(cur, {"idempotency_key": f"candidate:{got['provider']}|{got['sha256'][:16]}",
                                       "attributed_to": AGENT, "target_scope": SCOPE,
                                       "ops": [claim(LABEL, {"value": {"@value": got["name"]}}),
                                               claim(DCT + "source", {"entity": r["iri"]})]}, run_id)
                    outputs.update(experiment=got["id"], candidate=got["provider"], commit=sha, change_set=str(res["id"]))
                report[r["iri"]] = {"status": "built", **outputs}
            except Exception as e:                       # a failed run, recorded; go on with the next request
                report[r["iri"]] = {"status": "failed", "error": str(e)[:300]}
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build candidate providers for build requests.")
    ap.add_argument("--once", action="store_true", help="one pass, print the result and exit")
    a = ap.parse_args(argv)
    intent = Path(os.environ.get("KK_INTENT_DIR", ROOT / "morphogen" / "intent")).resolve()
    strategy = os.environ.get("KK_BUILDER_STRATEGY", "harness")
    fixtures = Path(os.environ["KK_BUILDER_FIXTURES"]).resolve() if os.environ.get("KK_BUILDER_FIXTURES") else None
    command = os.environ.get("KK_BUILDER_COMMAND")
    conn = connect(os.environ.get("KK_ROLE", "kkm_builder"))
    step = lambda c: print(json.dumps(one_pass(c, intent, strategy, fixtures, command), default=str), flush=True)
    if a.once:
        step(conn)
        return 0
    follow(conn, step, wake=lambda e: DCT + "type" in (e["predicates"] or []))
    return 0


if __name__ == "__main__":
    sys.exit(main())
