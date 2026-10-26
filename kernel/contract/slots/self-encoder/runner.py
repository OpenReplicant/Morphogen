"""The self-encoder slot's own runner (set.yaml `runner:`): runs one provider's scan over a small repository as its own
role and reads what it recorded. Prints "ok: <case id>" per passing case. Never imports the provider.

  python3 runner.py <provider directory>
"""
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from harness import Record, check  # noqa: E402

C = "urn:kk:contract:self-encoder/"
KK = "https://w3id.org/knowledge-kernel/ns#"
TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
VERSION = "http://www.w3.org/2002/07/owl#versionInfo"
PART_OF = "http://purl.org/dc/terms/isPartOf"
HAS_PART = "http://purl.org/dc/terms/hasPart"

BLUEPRINT = """# a blueprint
version: 0.1.0
slots:
  - id: store
    core: true
    cardinality: one
    interface: Store
    default: alpha
    contract: provider-tests
  - id: index           # a comment after the id
    cardinality: many
    interface: Index
    default: none
    contract: none
    why: nothing needs it yet
"""
ALPHA = """id: urn:kk:provider:alpha
name: Alpha
version: 1.2.0
license: Apache-2.0
slots: [store]
emits: [kkt:NodeTemplate, sosa:hasSimpleResult]
consumes: [kkt:connectsTo, {term: bbo:maxValue, optional: true, from: people}]
"""
BETA = """id: urn:kk:provider:beta
name: Beta
version: 0.3.0
license: MIT
slots:
  - store
  - index
"""
DIST = """id: demo
version: 0.9.0
uses_kernel_slots:
  - store
slots:
  - id: watcher
    phase: monitor
    cardinality: many
    default: gamma
    contract: provider-tests
"""


def cited(c: dict, line: str) -> bool:
    """Does the cited line name the fact: a slot's id (its comment: the default or why line), a provider's slot
    (or its `slots:` line), a value as written, a licence's line, a distribution's part?"""
    name = c["subject"].rsplit(":", 1)[-1]
    p, obj = c["predicate"], c["object_entity"] and c["object_entity"].rsplit(":", 1)[-1]
    if p == "http://www.w3.org/2000/01/rdf-schema#comment":
        return bool(re.match(r"\s+(default|why):", line))
    if p == "http://purl.org/dc/terms/license":
        return line.startswith("license:") and c["object_entity"].rsplit("/", 1)[-1] in line
    if p in (KK + "emits", KK + "consumes", KK + "mayConsume"):
        local = re.split(r"[#/]", c["object_entity"])[-1]
        return line.startswith("emits:" if p == KK + "emits" else "consumes:") and local in line
    if p in (KK + "fills", HAS_PART):
        return obj in line or line.strip() == "slots:"
    if c["subject"].startswith("urn:kk:slot:"):
        return re.search(rf"- id: {re.escape(name)}\b", line) is not None
    return bool(c["v"]) and c["v"] in line


def main(provider: Path) -> int:
    rec = Record("kkc_self_encoder", [provider])
    repo = Path(tempfile.mkdtemp(prefix="kkc-self-"))
    try:
        (repo / "kernel/blueprint").mkdir(parents=True)
        (repo / "kernel/blueprint/slots.yaml").write_text(BLUEPRINT)
        for name, text in (("alpha", ALPHA), ("beta", BETA)):
            (repo / f"kernel/providers/{name}").mkdir(parents=True)
            (repo / f"kernel/providers/{name}/provider.yaml").write_text(text)
        (repo / "demo.yaml").write_text(DIST)
        me = rec.agent_of(provider)

        def scan():
            since = rec.now()
            rec.service_once(provider, args=("scan", "--repo", str(repo), "--distribution", str(repo / "demo.yaml")))
            return since

        def current(subject=None, predicate=None):
            return rec.rows("select id::text, subject, predicate, object_entity, object_value->>'@value' v, evidence_type "
                            "from api.claims where attributed_to = %s and status <> 'deprecated'"
                            " and (%s::text is null or subject = %s) and (%s::text is null or predicate = %s)",
                            (me, subject, subject, predicate, predicate))

        def objects(subject, predicate):
            return sorted((r["object_entity"] or r["v"]) for r in current(subject, predicate))
        scan()
        ok = True
        slots = {s: {p: objects(f"urn:kk:slot:{s}", p) for p in (TYPE, LABEL, KK + "cardinality", KK + "slotContract", PART_OF)}
                 for s in ("store", "index")}
        ok &= check(slots == {"store": {TYPE: [KK + "Slot"], LABEL: ["store"], KK + "cardinality": ["one"],
                                        KK + "slotContract": ["Store"], PART_OF: ["urn:kk:blueprint:kernel"]},
                              "index": {TYPE: [KK + "Slot"], LABEL: ["index"], KK + "cardinality": ["many"],
                                        KK + "slotContract": ["Index"], PART_OF: ["urn:kk:blueprint:kernel"]}},
                    C + "slots", str(slots))
        fills = {p: (objects(f"urn:kk:provider:{p}", KK + "fills"), objects(f"urn:kk:provider:{p}", VERSION)) for p in ("alpha", "beta")}
        ok &= check(fills == {"alpha": (["urn:kk:slot:store"], ["1.2.0"]),
                              "beta": (["urn:kk:slot:index", "urn:kk:slot:store"], ["0.3.0"])}, C + "fills", str(fills))
        lines = {p: objects("urn:kk:provider:alpha", KK + p) for p in ("emits", "consumes", "mayConsume")}
        ok &= check(lines == {"emits": ["http://www.w3.org/ns/sosa/hasSimpleResult", "https://w3id.org/knowledge-kernel/tosca#NodeTemplate"],
                              "consumes": ["https://w3id.org/knowledge-kernel/tosca#connectsTo"],
                              "mayConsume": ["https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue"]}
                    and not current("urn:kk:provider:beta", KK + "emits"), C + "dependency-lines", str(lines))
        parts = objects("urn:kk:distribution:demo", HAS_PART)
        ok &= check(parts == ["urn:kk:slot:store", "urn:kk:slot:watcher"]
                    and objects("urn:kk:slot:watcher", TYPE) == [KK + "Slot"]
                    and objects("urn:kk:slot:watcher", PART_OF) == ["urn:kk:distribution:demo"], C + "distribution",
                    f"{parts} {objects('urn:kk:slot:watcher', PART_OF)}")

        bad = []
        everything = current()
        for c in everything:
            refs = rec.rows("select source_uri, span from kernel.claim_reference where claim_id = %s::uuid", (c["id"],))
            m = [(r["source_uri"], re.fullmatch(r"line=(\d+)", (r["span"] or {}).get("value", ""))) for r in refs]
            if c["evidence_type"] != "deterministic" or len(m) != 1 or not m[0][1] or not m[0][0].startswith("file:"):
                bad.append((c["subject"], c["predicate"], refs))
                continue
            path, n = repo / m[0][0][len("file:"):], int(m[0][1].group(1))
            lines = path.read_text().splitlines() if path.is_file() else []
            line = lines[n - 1] if 0 < n <= len(lines) else ""
            if not cited(c, line):
                bad.append((c["subject"], c["predicate"], line))
        ok &= check(everything and not bad, C + "cites-lines", str(bad[:4]))

        since = scan()
        again = rec.rows("select id from kernel.change_set where attributed_to = %s and submitted_at > %s::timestamptz", (me, since))
        ok &= check(not again, C + "same-content", f"{len(again)} new change sets")

        (repo / "kernel/blueprint/slots.yaml").write_text(BLUEPRINT.replace("cardinality: many", "cardinality: one"))
        old = [r["id"] for r in current("urn:kk:slot:index", KK + "cardinality")]
        scan()
        ok &= check(objects("urn:kk:slot:index", KK + "cardinality") == ["one"] and old
                    and all(r["status"] == "deprecated" for r in rec.rows("select status from api.claims where id = any(%s::uuid[])", (old,))),
                    C + "changed", str(objects("urn:kk:slot:index", KK + "cardinality")))

        shutil.rmtree(repo / "kernel/providers/beta")
        scan()
        ok &= check(not current("urn:kk:provider:beta") and objects("urn:kk:provider:alpha", KK + "fills") == ["urn:kk:slot:store"],
                    C + "removed", str(current("urn:kk:provider:beta")))
        return 0 if ok else 1
    finally:
        rec.drop()
        shutil.rmtree(repo, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
