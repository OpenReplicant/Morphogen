"""The mapping-set slot's own runner (set.yaml `runner:`): runs one provider's import of small SSSOM/TSV files as its
own role, approves as a person, and reads what was recorded. Prints "ok: <case id>" per passing case. Never imports
the provider.

  python3 runner.py <provider directory>
"""
import hashlib
import re
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from harness import Record, check, dump  # noqa: E402

C = "urn:kk:contract:mapping-set/"
SKOS = "http://www.w3.org/2004/02/skos/core#"
SSSOM = "https://w3id.org/sssom/"
A, B = "https://a.example/", "https://b.example/"
HEAD = """# curie_map:
#   A: https://a.example/
#   B: https://b.example/
# mapping_set_id: https://example.org/contract.sssom.tsv
# license: https://creativecommons.org/licenses/by/4.0/
# mapping_tool: https://example.org/matcher
subject_id\tpredicate_id\tobject_id\tmapping_justification\tconfidence\tpredicate_modifier
"""
V1 = HEAD + """A:1\tskos:exactMatch\tB:1\tsemapv:ManualMappingCuration\t0.9\t
A:2\towl:equivalentClass\tB:2\tsemapv:ManualMappingCuration\t\t
A:3\tskos:broadMatch\tB:3\tsemapv:LexicalMatching\t0.6\t
A:4\tskos:closeMatch\tB:4\tsemapv:LexicalMatching\t\tNot
A:5\tskos:narrowMatch\tB:5\tsemapv:ManualMappingCuration\t\t
"""
V2 = HEAD + """A:1\tskos:exactMatch\tB:1\tsemapv:ManualMappingCuration\t0.9\t
A:5\tskos:narrowMatch\tB:5\tsemapv:ManualMappingCuration\t\t
A:6\tskos:relatedMatch\tB:6\tsemapv:ManualMappingCuration\t\t
"""


def main(provider: Path) -> int:
    rec = Record("kkc_mapping_set", [provider])
    work = Path(tempfile.mkdtemp(prefix="kkc-sssom-"))
    try:
        me = rec.agent_of(provider)
        person = rec.agent("kkc_ms_reviewer", "urn:kk:agent:contract-reviewer", kind="person", grants=("kk_agent", "kk_reviewer"))

        def imp(name: str, text: str):
            (work / name).write_text(text)
            return rec.service_once(provider, args=("import", str(work / name)), env={"KK_ARTIFACTS": str(work / "artifacts")})

        def mine(status: str | None = None):
            return rec.rows("select id::text, subject, predicate, object_entity, qualifiers, scope, evidence_type, change_set::text "
                            "from api.claims where attributed_to = %s and status <> 'deprecated'", (me,))

        def sets():
            return rec.rows("select id::text, status, ops from kernel.change_set where attributed_to = %s order by submitted_at", (me,))

        def approve(cs_id: str):
            with rec.connect(person) as conn:
                conn.execute("select api.review(%s, true, 'contract: reviewed')", (cs_id,))

        ok = True
        imp("v1.sssom.tsv", V1)
        first = sets()
        ok &= check(len(first) == 1 and first[0]["status"] == "awaiting_review" and not mine(), C + "proposed",
                    dump(first) + dump(mine()))
        approve(first[0]["id"])
        got = {(c["subject"], c["predicate"], c["object_entity"]): c for c in mine()}
        ok &= check(set(got) == {(A + "1", SKOS + "exactMatch", B + "1"), (A + "3", SKOS + "broadMatch", B + "3"),
                                 (A + "5", SKOS + "narrowMatch", B + "5")}, C + "one-per-mapping", dump(sorted(got)))
        q1 = got.get((A + "1", SKOS + "exactMatch", B + "1"), {}).get("qualifiers") or {}
        q5 = got.get((A + "5", SKOS + "narrowMatch", B + "5"), {}).get("qualifiers") or {}
        ok &= check(q1 == {SSSOM + "mapping_justification": "https://w3id.org/semapv/vocab/ManualMappingCuration",
                           SSSOM + "confidence": 0.9, SSSOM + "mapping_tool": "https://example.org/matcher"}
                    and q5.get(SSSOM + "mapping_tool") == "https://example.org/matcher" and SSSOM + "confidence" not in q5,
                    C + "qualifiers", dump([q1, q5]))
        sha = hashlib.sha256(V1.encode()).hexdigest()
        lines = V1.split("\n")
        bad = []
        for c in got.values():
            refs = rec.rows("select r.source_uri, r.span, r.artifact, a.byte_size from kernel.claim_reference r "
                            "left join kernel.artifact a on a.sha256 = r.artifact where r.claim_id = %s::uuid", (c["id"],))
            n = re.fullmatch(r"line=(\d+)", ((refs[0]["span"] or {}).get("value") or "") if refs else "")
            row = lines[int(n.group(1)) - 1] if n else ""
            if (len(refs) != 1 or not refs[0]["source_uri"].endswith(f"v1.sssom.tsv#sha256={sha}")
                    or refs[0]["artifact"] != sha or refs[0]["byte_size"] != len(V1.encode())
                    or not row.startswith(c["subject"].replace(A, "A:") + "\t") or c["evidence_type"] != "deterministic"
                    or c["scope"] != "urn:kk:scope:vocab"):
                bad.append([c["subject"], refs, row, c["evidence_type"], c["scope"]])
        ok &= check(not bad and len(got) == 3, C + "cited", dump(bad))

        before = len(sets())
        try:
            imp("bad.sssom.tsv", V1.replace("A:3\t", "C:3\t").replace("contract.sssom", "other.sssom"))
            refused = False
        except SystemExit as e:
            refused = "refused" in str(e)
        ok &= check(refused and len(sets()) == before, C + "refused", f"refused {refused}, change sets {before} -> {len(sets())}")

        out = imp("v1-again.sssom.tsv", V1)
        ok &= check(len(sets()) == before and '"unchanged"' in out.stdout, C + "reimport", out.stdout[-400:])

        kept = got[(A + "1", SKOS + "exactMatch", B + "1")]["id"]
        imp("v2.sssom.tsv", V2)
        after = sets()
        last = after[-1]
        adds = [(o["subject"], o["predicate"]) for o in last["ops"] if o["op"] == "add_claim"]
        drops = sorted(o["claim"] for o in last["ops"] if o["op"] == "set_status")
        dropped = sorted(c["id"] for k, c in got.items() if k[0] == A + "3")
        waiting = len(after) == before + 1 and last["status"] == "awaiting_review"
        approve(last["id"])
        now = {(c["subject"], c["predicate"]): c["id"] for c in mine()}
        ok &= check(waiting and adds == [(A + "6", SKOS + "relatedMatch")] and drops == dropped
                    and set(now) == {(A + "1", SKOS + "exactMatch"), (A + "5", SKOS + "narrowMatch"), (A + "6", SKOS + "relatedMatch")}
                    and now[(A + "1", SKOS + "exactMatch")] == kept, C + "new-version",
                    dump({"waiting": waiting, "adds": adds, "drops": drops, "dropped": dropped, "now": sorted(now)}))
        return 0 if ok else 1
    finally:
        rec.drop()


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
