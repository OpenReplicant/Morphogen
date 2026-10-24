"""Self-encoder: records the kernel's own structure as claims, and answers from them. A plain command.

  python -m self_encoder scan [--repo DIR] [--distribution FILE ...] [--providers DIR ...]
      kernel/blueprint/slots.yaml, every kernel/providers/*/provider.yaml, every */provider.yaml under each
      --providers directory (a distribution's own providers) and each distribution file (paths relative to the
      repository) into one change set per file (encode.py): the same file again is a no-op, a changed (or
      reverted, or restored) file supersedes its earlier claims, a provider file gone from a directory scanned
      now is retracted, and a distribution is retracted only with --forget FILE.
  python -m self_encoder answer [SLOT ...]
      which provider fills each slot, from the self-encoder's own claims (what the files say; claims by other
      agents are not counted): every answer cites the claim ids it rests on, with their belief and the file and
      line each claim references (invariant 6). A slot asked for and not in the record says so.

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

from kk.changes import supersede
from kk.lib import connect, run, submit

from . import encode

MODULE = "urn:kk:module:self-encoder"
AGENT = "urn:kk:agent:self-encoder"
SCOPE = "urn:kk:scope:vocab"           # slot and provider descriptions (002_bootstrap.sql)
KEY = "self:"


def provider_dirs(repo: Path, extra: list[str] = ()) -> list[str]:
    """The provider directories scan reads, relative to the repository: the kernel's, then each one given."""
    return ["kernel/providers"] + [str(Path(d).resolve().relative_to(repo.resolve())) for d in extra]


def files(repo: Path, distributions: list[str], providers: list[str] = ()) -> list[tuple[str, str]]:
    """(relative path, kind) for every file scan reads."""
    out = [("kernel/blueprint/slots.yaml", "blueprint")]
    for d in provider_dirs(repo, providers):
        for p in sorted((repo / d).glob("*/provider.yaml")):
            if not p.parent.name.startswith("_"):
                out.append((str(p.relative_to(repo)), "provider"))
    out += [(str(Path(d).resolve().relative_to(repo.resolve())), "distribution") for d in distributions]
    for rel, _ in out:
        if "|" in rel:   # the change-set key separates the path from the content hash with |
            raise SystemExit(f"self-encoder: a path with '|' cannot be recorded: {rel}")
    return out


def ops_for(rel: str, kind: str, text: str) -> list[dict]:
    if kind == "blueprint":
        return encode.blueprint(rel, text)
    if kind == "provider":
        return encode.provider(rel, text, Path(rel).parent.name)
    return encode.distribution(rel, text)


# This agent's current claims from a file, and the last change set applied for it (by commit order).
CURRENT = """select c.id, c.subject, c.predicate, c.qualifiers, c.valid_from, c.status
             from api.claims c join api.change_sets s on s.id = c.change_set
             where c.attributed_to = %(agent)s and c.status <> 'deprecated' and starts_with(s.idempotency_key, %(prefix)s)"""
LAST = """select s.id::text, s.idempotency_key from api.change_sets s
          where s.attributed_to = %(agent)s and s.status = 'applied' and starts_with(s.idempotency_key, %(prefix)s)
          order by s.applied_at desc limit 1"""


def rows(cur, statement: str, args: dict) -> list[dict]:
    cur.execute(statement, args)
    cols = [d.name for d in cur.description]
    return [dict(zip(cols, r)) for r in cur.fetchall()]


def record(cur, rel: str, sha: str | None, ops: list[dict], info: dict) -> dict:
    """One change set for file `rel`: its claims (sha given) or none (the file is gone), superseding or
    retracting this agent's current claims from it. The key names the content and the change set it follows,
    so the same content after a different one (reverted, restored) is a new change set, and the same content
    again is a no-op."""
    prefix = f"{KEY}{rel}|"
    last = rows(cur, LAST, {"agent": AGENT, "prefix": prefix})
    after = last[0]["id"] if last else "first"
    if last and sha and last[0]["idempotency_key"].startswith(f"{prefix}{sha[:16]}|"):
        return {"file": rel, "change_set": last[0]["id"], "status": "unchanged", "claims": 0, "superseded": 0}
    prior = rows(cur, CURRENT, {"agent": AGENT, "prefix": prefix})
    if sha is None and not prior:
        return {"file": rel, "status": "nothing to retract"}
    cs = {"idempotency_key": f"{prefix}{sha[:16] if sha else 'removed'}|after:{after}", "attributed_to": AGENT,
          "target_scope": SCOPE, "ops": list(ops)}
    supersede(cs, prior)
    with run(cur, MODULE, info) as (run_id, outputs):
        res = submit(cur, cs, run_id)
        outputs.update(claims=len(ops), superseded=len(prior))
    return {"file": rel, "change_set": str(res["id"]), "status": res["status"], "claims": len(ops),
            "superseded" if sha else "retracted": len(prior)}


def scan(repo: Path, distributions: list[str], forget: list[str] = (), providers: list[str] = ()) -> list[dict]:
    """Record every file scan reads. Kernel files, and provider files under a directory scanned now, encoded
    before and gone from disk now are retracted; a distribution is retracted only when named in `forget`
    (another scan may simply not have been given it)."""
    results = []
    seen = files(repo, distributions, providers)
    scanned = tuple(d.rstrip("/") + "/" for d in provider_dirs(repo, providers))
    with connect(os.environ.get("KK_ROLE", "kkm_self_encoder")) as conn, conn.cursor() as cur:
        for rel, kind in seen:
            data = (repo / rel).read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            results.append(record(cur, rel, sha, ops_for(rel, kind, data.decode("utf-8")), {"file": rel, "sha256": sha}))
        cur.execute("select distinct split_part(substr(idempotency_key, %s), '|', 1) from api.change_sets "
                    "where attributed_to = %s and starts_with(idempotency_key, %s) and status = 'applied'",
                    (len(KEY) + 1, AGENT, KEY))
        current = {rel for rel, _ in seen}
        gone = [rel for (rel,) in cur.fetchall() if rel not in current and rel.startswith(("kernel/blueprint/", *scanned))
                and not (repo / rel).exists()]
        gone += [str(Path(f).resolve().relative_to(repo.resolve())) for f in forget]
        for rel in sorted(set(gone)):
            results.append(record(cur, rel, None, [], {"file": rel, "removed": True}))
    return results


# The self-encoder's own current claims (what the files say), so another agent's kk:fills does not count.
OWN = "attributed_to = %(agent)s and status <> 'deprecated'"
SLOTS = f"""select subject, id::text from api.claims
            where predicate = %(type)s and object_entity = %(slot)s and {OWN}"""
FILLS = f"""select object_entity, subject, id::text from api.claims where predicate = %(fills)s and {OWN}
            order by subject"""
NOTES = f"""select distinct on (subject) subject, id::text, object_value->>'@value' from api.claims
            where predicate = %(comment)s and {OWN} order by subject, recorded_at desc"""


def cite(conn, claim_id: str) -> dict:
    """A claim's id and belief (None: not scored yet) with the file and line it references (api.explain)."""
    ex = conn.execute("select api.explain(%s::uuid)", (claim_id,)).fetchone()[0]
    refs = [f"{r['source_uri']}#{(r.get('span') or {}).get('value', '')}".rstrip("#") for r in ex["references"]]
    return {"claim": claim_id, "belief": ex["claim"]["belief"], "source": refs}


def answer(conn, slots: list[str] | None = None) -> list[dict]:
    """Which provider fills each slot, every part cited (invariant 6). A slot asked for and not declared says
    so; a provider claimed to fill an undeclared slot is reported as such."""
    args = {"fills": encode.KK + "fills", "comment": encode.COMMENT, "type": encode.RDF_TYPE,
            "slot": encode.KK + "Slot", "agent": AGENT}
    declared = dict(conn.execute(SLOTS, args).fetchall())
    fills: dict = {}
    for slot, provider, claim_id in conn.execute(FILLS, args).fetchall():
        fills.setdefault(slot, []).append({"provider": provider, **cite(conn, claim_id)})
    notes = {s: (i, t) for s, i, t in conn.execute(NOTES, args).fetchall()}
    wanted = [encode.slot_iri(s) for s in slots] if slots else sorted(set(declared) | set(fills))
    out = []
    for slot in wanted:
        if slot not in declared:
            out.append({"slot": slot, "declared": None, "filled_by": fills.get(slot, []),
                        "note": "not declared in the record" + (" (yet providers claim to fill it)" if slot in fills else "")})
            continue
        item = {"slot": slot, "declared": cite(conn, declared[slot]), "filled_by": fills.get(slot, [])}
        if slot in notes:
            item["note"] = {"text": notes[slot][1], **cite(conn, notes[slot][0])}
        out.append(item)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sc = sub.add_parser("scan")
    sc.add_argument("--repo", default=".")
    sc.add_argument("--distribution", action="append", default=[])
    sc.add_argument("--forget", action="append", default=[], help="a distribution file to retract")
    sc.add_argument("--providers", action="append", default=[], help="a directory of provider directories")
    an = sub.add_parser("answer")
    an.add_argument("slots", nargs="*")
    a = ap.parse_args(argv)
    if a.cmd == "scan":
        for r in scan(Path(a.repo), a.distribution, a.forget, a.providers):
            print(json.dumps(r))
        return 0
    with connect(os.environ.get("KK_ROLE", "kkm_self_encoder")) as conn:
        print(json.dumps(answer(conn, a.slots or None), indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
