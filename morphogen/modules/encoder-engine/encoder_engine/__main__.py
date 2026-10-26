"""Encoder of what runs (R5-49): records what a container engine runs of a system as node representations
(encode.py), so the kernel's gap finder can compare it with the system's templates (the kk-tosca drift shapes).

  python3 -m encoder_engine scan --system NAME [--project NAME] [--compose FILE]
      the engine's running containers of the compose project (default kk-<system>, as the runtime names it) into
      one change set, a command or environment value recorded only where it is what FILE (the system's compose
      file) declares, else withheld (encode.py): the same view again is a no-op; a changed one supersedes this encoder's earlier claims about
      the system, and a service no longer running has its claims retracted.
  python3 -m encoder_engine watch --intent DIR [--every SECONDS]
      scans every system under DIR/systems (project kk-<system>) every SECONDS (default 30).

The engine is KK_ENGINE (default docker; podman takes the same commands), run with only PATH, HOME, DOCKER_HOST,
CONTAINER_HOST and XDG_RUNTIME_DIR (where rootless Podman finds its socket).
Env: DATABASE_URL (the provider's own login, or one that may SET ROLE to KK_ROLE), KK_ROLE (default
kkm_encoder_engine).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg

from kk.changes import supersede
from kk.lib import connect, run, submit

from . import encode

MODULE = "urn:kk:module:encoder-engine"
AGENT = "urn:kk:agent:encoder-engine"
SCOPE = "urn:kk:scope:default"
KEY = "engine:"
ENV = ("PATH", "HOME", "DOCKER_HOST", "CONTAINER_HOST", "XDG_RUNTIME_DIR")

CURRENT = """select c.id, c.subject, c.predicate, c.qualifiers, c.valid_from, c.status
             from api.claims c join api.change_sets s on s.id = c.change_set
             where c.attributed_to = %(agent)s and c.status <> 'deprecated' and starts_with(s.idempotency_key, %(prefix)s)"""
LAST = """select s.id::text, s.idempotency_key from api.change_sets s
          where s.attributed_to = %(agent)s and s.status = 'applied' and starts_with(s.idempotency_key, %(prefix)s)
          order by s.applied_at desc limit 1"""


def inspect(project: str) -> list[dict]:
    """The engine's containers of the compose project, as `inspect` gives them."""
    engine = os.environ.get("KK_ENGINE", "docker")
    env = {k: v for k, v in os.environ.items() if k in ENV}
    ids = subprocess.run([engine, "ps", "-q", "--filter", f"label={encode.PROJECT}={project}"], env=env,
                         capture_output=True, text=True, check=True, timeout=60).stdout.split()
    if not ids:
        return []
    out = subprocess.run([engine, "inspect", *ids], env=env, capture_output=True, text=True, check=True, timeout=60)
    return json.loads(out.stdout)


def rows(cur, statement: str, args) -> list[dict]:
    cur.execute(statement, args)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def record(system: str, project: str, containers: list[dict], compose: str | None = None) -> dict:
    """One change set for what runs of the system, superseding this encoder's current claims about it. `compose`:
    the system's compose file (its text), whose declared values may be recorded as they run."""
    ops = encode.representations(system, project, containers, os.environ.get("KK_ENGINE", "docker"), encode.declared(compose))
    sha = hashlib.sha256(json.dumps(ops, sort_keys=True).encode()).hexdigest()
    prefix = f"{KEY}{system}|"
    with connect(os.environ.get("KK_ROLE", "kkm_encoder_engine")) as conn, conn.cursor() as cur:
        last = rows(cur, LAST, {"agent": AGENT, "prefix": prefix})
        if last and last[0]["idempotency_key"].startswith(f"{prefix}{sha[:16]}|"):
            return {"system": system, "status": "unchanged", "claims": 0}
        prior = rows(cur, CURRENT, {"agent": AGENT, "prefix": prefix})
        if not ops and not prior:
            return {"system": system, "status": "nothing runs", "claims": 0}
        cs = {"idempotency_key": f"{prefix}{sha[:16]}|after:{last[0]['id'] if last else 'first'}", "attributed_to": AGENT,
              "target_scope": SCOPE, "ops": list(ops)}
        supersede(cs, prior)          # appends to cs["ops"]: the count below is of claims only
        with run(cur, MODULE, {"system": system, "project": project}) as (run_id, outputs):
            res = submit(cur, cs, run_id)
            outputs.update(claims=len(ops), superseded=len(prior))
    return {"system": system, "change_set": str(res["id"]), "status": res["status"], "claims": len(ops), "superseded": len(prior)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan")
    sc.add_argument("--system", required=True)
    sc.add_argument("--project")
    sc.add_argument("--compose")
    wa = sub.add_parser("watch")
    wa.add_argument("--intent", required=True)
    wa.add_argument("--every", type=float, default=30)
    a = ap.parse_args(argv)
    if a.cmd == "scan":
        project = a.project or f"kk-{a.system}"
        text = Path(a.compose).read_text() if a.compose else None
        print(json.dumps(record(a.system, project, inspect(project), text)))
        return 0
    while True:
        for f in sorted(Path(a.intent).glob("systems/*/compose.yaml")):
            name = f.parent.name
            try:
                print(json.dumps(record(name, f"kk-{name}", inspect(f"kk-{name}"), f.read_text())), flush=True)
            except (subprocess.SubprocessError, OSError, ValueError, psycopg.Error) as e:   # one system's failure, not the loop's
                print(json.dumps({"system": name, "error": f"{type(e).__name__}: {e}"}), flush=True)
        time.sleep(a.every)


if __name__ == "__main__":
    sys.exit(main())
