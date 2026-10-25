"""The vocabulary-pack slot's own runner (set.yaml `runner:`): installs one provider's migration on a record with nothing
else, and compares what it recorded with the pack files. Prints "ok: <case id>" per passing case. Never imports the
provider.

  python3 runner.py <provider directory>
"""
import hashlib
import sys
from pathlib import Path

import rdflib
import yaml
from rdflib import Literal, URIRef

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from harness import KERNEL, Record, check, meta  # noqa: E402

C = "urn:kk:contract:vocabulary-pack/"
REPO = KERNEL.parent
RDF_TYPE = str(rdflib.RDF.type)
PROPERTY_TYPES = {str(rdflib.RDF.Property), str(rdflib.OWL.ObjectProperty), str(rdflib.OWL.DatatypeProperty),
                  str(rdflib.OWL.AnnotationProperty)}


def packs() -> list[Path]:
    spec = yaml.safe_load((KERNEL / "packs" / "packs.yaml").read_text())
    return [KERNEL / "packs" / p["file"] for tier in ("core", "profile") for p in spec.get(tier, []) if "file" in p]


def key(s, p, o) -> tuple:
    if isinstance(o, URIRef):
        return (str(s), str(p), "entity", str(o))
    if isinstance(o, Literal):
        return (str(s), str(p), "value", str(o))
    return (str(s), str(p), "blank", str(o))


def main(provider: Path) -> int:
    if not meta(provider).get("migration"):
        print(f"FAIL: {provider}/provider.yaml names no migration")
        return 1
    rec = Record("kkc_packs", [provider], packs=False)
    try:
        role = meta(provider).get("role")
        agent = rec.rows("select iri from kernel.agent where db_role = %s", (role,)) if role else []
        if not agent:
            print(f"FAIL: {provider}/provider.yaml names no `role:` mapped to an agent")
            return 1
        me = agent[0]["iri"]
        want, pins, typed = {}, {}, set()
        for f in packs():
            rel = f.relative_to(REPO).as_posix()
            pins[rel] = hashlib.sha256(f.read_bytes()).hexdigest()
            for s, p, o in rdflib.Graph().parse(f):
                want[key(s, p, o)] = rel
                if str(p) == RDF_TYPE and str(o) in PROPERTY_TYPES:
                    typed.add(str(s))
        rows = rec.rows("""select c.id, c.subject, c.predicate, c.object_entity, c.object_value->>'@value' v, c.scope,
                                  c.evidence_type, c.attributed_to, c.status, array_agg(r.source_uri) refs
                           from api.claims c left join kernel.claim_reference r on r.claim_id = c.id
                           where c.attributed_to = %s group by c.id, c.subject, c.predicate, c.object_entity, c.object_value,
                                 c.scope, c.evidence_type, c.attributed_to, c.status""", (me,))
        got = {(r["subject"], r["predicate"], "entity" if r["object_entity"] else "value", r["object_entity"] or r["v"]): r
               for r in rows if r["status"] != "deprecated" and r["scope"] == "urn:kk:scope:vocab"}
        ok = True
        missing, extra = set(want) - set(got), set(got) - set(want)
        ok &= check(want and not missing and not extra, C + "complete",
                    f"{len(missing)} triples missing (e.g. {sorted(missing)[:2]}), {len(extra)} claims no pack says (e.g. {sorted(extra)[:2]})")
        stale = [(k, r["refs"]) for k, r in got.items() if k in want
                 and f"file:{want[k]}#sha256={pins[want[k]]}" not in (r["refs"] or [])]
        ok &= check(got and not stale, C + "pinned", f"{len(stale)} claims not pinned to their file as it is now, e.g. {stale[:1]}")
        ok &= check(rows and all(r["evidence_type"] == "deterministic" for r in rows), C + "attributed",
                    str({r["evidence_type"] for r in rows}))
        approved = {p: rec.rows("select kernel.is_approved_property(%s) a", (p,))[0]["a"] for p in sorted(typed)}
        ok &= check(typed and all(approved.values()), C + "properties-approved",
                    str([p for p, a in approved.items() if not a][:5]))
        never = ["https://w3id.org/knowledge-kernel/ns#notATerm", "https://w3id.org/knowledge-kernel/tosca#notATerm",
                 "http://www.w3.org/ns/sosa/notATerm", "urn:x:made-up-property"]
        ok &= check(not any(rec.rows("select kernel.is_approved_property(%s) a", (p,))[0]["a"] for p in never),
                    C + "nothing-else-approved", "a property no pack types is approved")
        before = rec.rows("select count(*) n from kernel.claim")[0]["n"]
        rec.psql("-f", str(provider / meta(provider)["migration"]))
        after = rec.rows("select count(*) n from kernel.claim")[0]["n"]
        ok &= check(before == after, C + "reinstall", f"{after - before} more claims")
        return 0 if ok else 1
    finally:
        rec.drop()


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
