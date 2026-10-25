"""Compose encoder: records a system's compose file as a TOSCA topology (encode.py), and answers from it.
A plain command.

  python -m encoder_compose scan --system NAME --file FILE [--repo DIR]
      FILE (cited relative to DIR, default .) into one change set: the same content again is a no-op; a
      changed file supersedes this encoder's earlier claims about the system.
  python -m encoder_compose scan --system NAME --file FILE [--repo DIR] --adopt
      also asks a person, in the review lane, to approve the file as it is (an adopt-system plan naming its
      sha256): a runtime runs only a file an approved step names (T26). For a file a person brought in.
  python -m encoder_compose answer SYSTEM
      the system's services: each one's image, settings and what it connects to, from this encoder's own
      claims, every part citing its claim id, belief and file line (invariant 6).

Env: DATABASE_URL (the provider's own login, or one that may SET ROLE to KK_ROLE), KK_ROLE (default
kkm_encoder_compose).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from kk.changes import supersede
from kk.lib import connect, run, submit

from . import encode

MODULE = "urn:kk:module:encoder-compose"
AGENT = "urn:kk:agent:encoder-compose"
SCOPE = "urn:kk:scope:default"
KEY = "compose:"

CURRENT = """select c.id, c.subject, c.predicate, c.qualifiers, c.valid_from, c.status
             from api.claims c join api.change_sets s on s.id = c.change_set
             where c.attributed_to = %(agent)s and c.status <> 'deprecated' and starts_with(s.idempotency_key, %(prefix)s)"""
LAST = """select s.id::text, s.idempotency_key from api.change_sets s
          where s.attributed_to = %(agent)s and s.status = 'applied' and starts_with(s.idempotency_key, %(prefix)s)
          order by s.applied_at desc limit 1"""


def rows(cur, statement: str, args) -> list[dict]:
    cur.execute(statement, args)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def scan(system: str, file: Path, repo: Path) -> dict:
    """One change set for the system's compose file, superseding this encoder's current claims about it."""
    rel = str(file.resolve().relative_to(repo.resolve()))
    data = file.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    ops = encode.compose(rel, data.decode("utf-8"), system)
    prefix = f"{KEY}{system}|"
    with connect(os.environ.get("KK_ROLE", "kkm_encoder_compose")) as conn, conn.cursor() as cur:
        last = rows(cur, LAST, {"agent": AGENT, "prefix": prefix})
        if last and last[0]["idempotency_key"].startswith(f"{prefix}{sha[:16]}|"):
            return {"system": system, "file": rel, "change_set": last[0]["id"], "status": "unchanged", "claims": 0}
        prior = rows(cur, CURRENT, {"agent": AGENT, "prefix": prefix})
        cs = {"idempotency_key": f"{prefix}{sha[:16]}|after:{last[0]['id'] if last else 'first'}", "attributed_to": AGENT,
              "target_scope": SCOPE, "ops": ops}
        supersede(cs, prior)
        with run(cur, MODULE, {"system": system, "file": rel, "sha256": sha}) as (run_id, outputs):
            res = submit(cur, cs, run_id)
            outputs.update(claims=len(ops), superseded=len(prior))
    return {"system": system, "file": rel, "change_set": str(res["id"]), "status": res["status"], "claims": len(ops),
            "superseded": len(prior)}


def cite(conn, claim_id: str) -> dict:
    ex = conn.execute("select api.explain(%s::uuid)", (claim_id,)).fetchone()[0]
    refs = [f"{r['source_uri']}#{(r.get('span') or {}).get('value', '')}".rstrip("#") for r in ex["references"]]
    return {"claim": claim_id, "belief": ex["claim"]["belief"], "source": refs}


def answer(conn, system: str) -> dict:
    """{system, services: {name: {node, image, settings, connects_to}}}, every value with its citation."""
    q = lambda sql, *a: conn.execute(sql, a).fetchall()
    own = "attributed_to = %s and status <> 'deprecated'"
    nodes = q(f"select subject, id::text from api.claims where predicate = %s and object_entity = %s and {own}",
              encode.KKT + "memberOf", encode.system_iri(system), AGENT)
    out = {"system": system, "services": {}}
    for node, member in sorted(nodes):
        props = q(f"select qualifiers->>%s, object_value->>'@value', id::text from api.claims "
                  f"where subject = %s and predicate = %s and {own} order by 1", encode.KKT + "propertyName", node,
                  encode.KKT + "propertyValue", AGENT)
        links = q(f"select object_entity, id::text from api.claims where subject = %s and predicate = %s and {own} order by 1",
                  node, encode.KKT + "connectsTo", AGENT)
        settings = {name: {"value": v, **cite(conn, i)} for name, v, i in props}
        out["services"][node.rsplit(":", 1)[-1]] = {
            "node": node, "member_of": cite(conn, member), "image": settings.pop("image", None),
            "command": settings.pop("command", None), "settings": settings,
            "connects_to": [{"node": o, **cite(conn, i)} for o, i in links]}
    return out


def propose_adopt(system: str, file: Path, repo: Path) -> dict:
    """An adopt-system plan for the file's exact content, in the review lane; the same content again is a no-op."""
    rel = str(file.resolve().relative_to(repo.resolve()))
    data = file.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    plan, ops = encode.adopt(rel, data.decode("utf-8"), system, sha)
    with connect(os.environ.get("KK_ROLE", "kkm_encoder_compose")) as conn, conn.cursor() as cur:
        with run(cur, MODULE, {"system": system, "file": rel, "sha256": sha, "adopt": True}) as (run_id, outputs):
            res = submit(cur, {"idempotency_key": f"adopt:{system}:{sha}", "attributed_to": AGENT, "target_scope": SCOPE,
                               "lane": "review", "ops": ops}, run_id)
            outputs.update(plan=plan, change_set=str(res["id"]))
    return {"plan": plan, "change_set": str(res["id"]), "sha256": sha}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan")
    sc.add_argument("--system", required=True)
    sc.add_argument("--file", required=True)
    sc.add_argument("--repo", default=".")
    sc.add_argument("--adopt", action="store_true", help="also propose running the file as it is (review lane)")
    an = sub.add_parser("answer")
    an.add_argument("system")
    a = ap.parse_args(argv)
    if a.cmd == "scan":
        out = scan(a.system, Path(a.file), Path(a.repo))
        if a.adopt:
            out["adopt"] = propose_adopt(a.system, Path(a.file), Path(a.repo))
        print(json.dumps(out))
        return 0
    with connect(os.environ.get("KK_ROLE", "kkm_encoder_compose")) as conn:
        print(json.dumps(answer(conn, a.system), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
