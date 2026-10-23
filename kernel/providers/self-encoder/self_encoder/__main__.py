"""Self-encoder: records the kernel's own structure as claims, and answers from them. A plain command.

  python -m self_encoder scan [--repo DIR] [--distribution FILE ...]
      kernel/blueprint/slots.yaml, every kernel/providers/*/provider.yaml and each distribution file (paths
      relative to the repository) into one change set per file (encode.py), keyed by the file's path and hash:
      the same file again is a no-op, a changed file supersedes its earlier claims, a removed one retracts them.
  python -m self_encoder answer [SLOT ...]
      which provider fills each slot, from the record: every answer cites the claim ids it rests on, with their
      belief and the file and line each claim references (invariant 6).

Env: DATABASE_URL (the provider's own login, or one that may SET ROLE to KK_ROLE), KK_ROLE (default
kkm_self_encoder). The ingest filter (rebuild 4 ran gitleaks first) is not ported yet: scan reads only the
blueprint, provider manifests and the distribution files it is given.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from kk.changes import prior as prior_claims, supersede
from kk.lib import connect, run, submit

from . import encode

MODULE = "urn:kk:module:self-encoder"
AGENT = "urn:kk:agent:self-encoder"
SCOPE = "urn:kk:scope:default"
KEY = "self:"


def files(repo: Path, distributions: list[str]) -> list[tuple[str, str]]:
    """(relative path, kind) for every file scan reads."""
    out = [("kernel/blueprint/slots.yaml", "blueprint")]
    for p in sorted((repo / "kernel" / "providers").glob("*/provider.yaml")):
        if not p.parent.name.startswith("_"):
            out.append((str(p.relative_to(repo)), "provider"))
    out += [(str(Path(d).resolve().relative_to(repo.resolve())), "distribution") for d in distributions]
    return out


def ops_for(rel: str, kind: str, text: str) -> list[dict]:
    if kind == "blueprint":
        return encode.blueprint(rel, text)
    if kind == "provider":
        return encode.provider(rel, text, Path(rel).parent.name)
    return encode.distribution(rel, text)


def scan(repo: Path, distributions: list[str]) -> list[dict]:
    results = []
    seen = files(repo, distributions)
    with connect(os.environ.get("KK_ROLE", "kkm_self_encoder")) as conn, conn.cursor() as cur:
        for rel, kind in seen:
            data = (repo / rel).read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            key, prefix = f"{KEY}{rel}|{sha[:16]}", f"{KEY}{rel}|"
            cs = {"idempotency_key": key, "attributed_to": AGENT, "target_scope": SCOPE,
                  "ops": ops_for(rel, kind, data.decode("utf-8"))}
            with run(cur, MODULE, {"file": rel, "sha256": sha}) as (run_id, outputs):
                prior = prior_claims(cur, AGENT, prefix, key)
                if prior:
                    supersede(cs, prior)
                res = submit(cur, cs, run_id)
                outputs.update(claims=sum(op["op"] == "add_claim" for op in cs["ops"]), superseded=len(prior))
            results.append({"file": rel, "change_set": str(res["id"]), "status": res["status"],
                            "claims": outputs["claims"], "superseded": len(prior)})
        # Files encoded before and gone now: their claims are retracted.
        cur.execute("select distinct split_part(substr(idempotency_key, %s), '|', 1) from api.change_sets "
                    "where attributed_to = %s and starts_with(idempotency_key, %s) and status = 'applied'",
                    (len(KEY) + 1, AGENT, KEY))
        current = {rel for rel, _ in seen}
        for (rel,) in cur.fetchall():
            if rel in current:
                continue
            prior = prior_claims(cur, AGENT, f"{KEY}{rel}|", "")
            if not prior:
                continue
            cs = {"idempotency_key": f"{KEY}{rel}|removed|{len(prior)}|{prior[0]['id']}", "attributed_to": AGENT,
                  "target_scope": SCOPE, "ops": []}
            supersede(cs, prior)
            with run(cur, MODULE, {"file": rel, "removed": True}) as (run_id, outputs):
                res = submit(cur, cs, run_id)
                outputs.update(retracted=len(prior))
            results.append({"file": rel, "change_set": str(res["id"]), "status": res["status"], "retracted": len(prior)})
    return results


ANSWER = """select s.subject, s.id, s.belief,
                  (select jsonb_agg(jsonb_build_object('provider', f.subject, 'claim', f.id, 'belief', f.belief)
                                    order by f.subject)
                     from api.claims f where f.predicate = %(fills)s and f.object_entity = s.subject
                       and f.status <> 'deprecated'),
                  (select jsonb_build_object('text', c.object_value->>'@value', 'claim', c.id, 'belief', c.belief)
                     from api.claims c where c.subject = s.subject and c.predicate = %(comment)s
                       and c.status <> 'deprecated' order by c.recorded_at desc limit 1)
           from api.claims s
           where s.predicate = %(type)s and s.object_entity = %(slot)s and s.status <> 'deprecated'
             and (%(only)s::text[] is null or s.subject = any(%(only)s))
           order by s.subject"""


def cite(conn, claim_id: str) -> dict:
    """A claim's id and belief with the file and line it references (api.explain)."""
    ex = conn.execute("select api.explain(%s::uuid)", (claim_id,)).fetchone()[0]
    refs = [f"{r['source_uri']}#{(r.get('span') or {}).get('value', '')}".rstrip("#") for r in ex["references"]]
    return {"claim": claim_id, "belief": ex["claim"]["belief"], "source": refs}


def answer(conn, slots: list[str] | None = None) -> list[dict]:
    """Which provider fills each slot, every part cited (invariant 6)."""
    rows = conn.execute(ANSWER, {"fills": encode.KK + "fills", "comment": encode.COMMENT, "type": encode.RDF_TYPE,
                                 "slot": encode.KK + "Slot",
                                 "only": [encode.slot_iri(s) for s in slots] if slots else None}).fetchall()
    out = []
    for slot, type_claim, _, fills, note in rows:
        item = {"slot": slot, "declared": cite(conn, str(type_claim)),
                "filled_by": [{"provider": f["provider"], **cite(conn, f["claim"])} for f in (fills or [])]}
        if note:
            item["note"] = {"text": note["text"], **cite(conn, note["claim"])}
        out.append(item)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan")
    sc.add_argument("--repo", default=".")
    sc.add_argument("--distribution", action="append", default=[])
    an = sub.add_parser("answer")
    an.add_argument("slots", nargs="*")
    a = ap.parse_args(argv)
    if a.cmd == "scan":
        for r in scan(Path(a.repo), a.distribution):
            print(json.dumps(r))
        return 0
    with connect(os.environ.get("KK_ROLE", "kkm_self_encoder")) as conn:
        print(json.dumps(answer(conn, a.slots or None), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
