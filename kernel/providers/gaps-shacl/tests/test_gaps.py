"""The shape-driven gap finder's own tests (R5-O18 (5), R5-47): rules the gap-finder cases do not reach, what the
finder takes from a shape (kind, question, order, premises), and the predicates a service reads. Its parity with
Morphogen's map-gaps is checked in that distribution, next to map-gaps.

  python3 tests/test_gaps.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
KERNEL = HERE.parents[1]
sys.path[:0] = [str(HERE), str(KERNEL / "contract" / "slots" / "gap-finder"), str(KERNEL / "src")]
from gaps_shacl.gaps import ShapeError, gaps, reads, shapes  # noqa: E402
from runner import claims, node  # noqa: E402

RULES = shapes()
KIND = "urn:kk:gap-kind:"


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def found(services):
    return {(g["kind"].removeprefix(KIND), g["target"]) for g in gaps(claims(services), RULES)}


short = "example/web:1@sha256:" + "a" * 12
check(("unpinned-image", node("shop/web")) in found({"shop/web": {"image": short, "limit": True}}),
      "an image with a shortened digest is not pinned")
check(("unpinned-image", node("shop/web")) not in found({"shop/web": {"image": "example/web:1@sha256:" + "a" * 64, "limit": True}}),
      "an image with a whole digest is pinned")
check(("unconnected", node("shop/back")) in found({"shop/front": {"image": True, "limit": True},
                                                    "shop/back": {"image": True},
                                                    "ops/probe": {"image": True, "limit": True, "connects": ["shop/back"]}}),
      "a service called only from another system, calling nothing, is unconnected in its own")

got = gaps(claims({"shop/front": {"image": True, "connects": ["shop/pay"]}}), RULES)
peer = next(g for g in got if g["kind"] == KIND + "unknown-peer")
state = {c["id"]: c for c in claims({"shop/front": {"image": True, "connects": ["shop/pay"]}})}
check(peer["target"] == node("shop/pay") and peer["premises"]
      and all(state[p]["object_entity"] == node("shop/pay") for p in peer["premises"]),
      "a gap on the objects of a predicate derives from the claims pointing at it")
check("front" in next(g["text"] for g in got if g["kind"] == KIND + "no-limit") and "{this}" not in peer["text"],
      "the question names its target by label")
check([g["kind"].removeprefix(KIND) for g in got] == ["unknown-peer", "no-limit"], f"gaps come in the shapes' order: {got}")

from gaps_shacl.gaps import ShapeError  # noqa: E402
from rdflib import Graph  # noqa: E402

KKT, P = "https://w3id.org/knowledge-kernel/tosca#", "urn:kk:node:shop:web"
state = claims({"shop/web": {"image": "example/web:1", "settings": {"LOG": "debug"}, "prediction": True}})
by = {c["id"]: c for c in state}
for g in gaps(state, RULES):
    preds = {by[i]["predicate"] for i in g["premises"]}
    check(preds == {"http://www.w3.org/1999/02/22-rdf-syntax-ns#type", KKT + "memberOf"},
          f"{g['kind'].removeprefix(KIND)} rests only on the claims that put the service on the map, never a label, "
          f"another setting or a plan's prediction: {sorted(preds)}")
check(("unpinned-image", P) in found({"shop/web": {"image": "example/web:1@sha256:" + "a" * 64 + "\n", "limit": True}}),
      "a digest followed by a line break is not a pin (the runtimes match the whole value)")
two = claims({"shop/front": {"image": True, "limit": True}, "shop/back": {"image": True, "limit": True}})
two.append({"id": "q1", "subject": node("shop/front"), "predicate": KKT + "connectsTo", "object_entity": node("shop/back"),
            "object_value": None, "qualifiers": {"urn:kk:q:protocol": "http"}})
two.append({"id": "q2", "subject": node("shop/front"), "predicate": KKT + "connectsTo", "object_entity": None,
            "object_value": {"@value": "urn:kk:node:shop:ghost"}, "qualifiers": {}})
got = gaps(two, RULES)
check(not got, f"a qualified connection still reaches the service it names, and one to a literal is no gap on nothing: {got}")
blank = Graph().parse(data="""@prefix sh: <http://www.w3.org/ns/shacl#> . @prefix dcterms: <http://purl.org/dc/terms/> .
<urn:test:NoPremises> a sh:PropertyShape ; sh:targetClass <https://w3id.org/knowledge-kernel/tosca#NodeTemplate> ;
    sh:path <http://www.w3.org/2000/01/rdf-schema#comment> ; sh:minCount 1 ; sh:severity sh:Warning ;
    dcterms:type <urn:kk:gap-kind:untold> .""", format="turtle")
try:
    gaps(claims({"shop/web": {"image": True}}), RULES + blank)
    check(False, "a warning shape without premises is refused")
except ShapeError:
    check(True, "a warning shape without premises is refused")
hard = Graph().parse(data="""@prefix sh: <http://www.w3.org/ns/shacl#> . @prefix dcterms: <http://purl.org/dc/terms/> .
<urn:test:NeedsLabel> a sh:PropertyShape ; sh:targetClass <https://w3id.org/knowledge-kernel/tosca#NodeTemplate> ;
    sh:path <http://www.w3.org/2000/01/rdf-schema#comment> ; sh:minCount 1 ; sh:severity sh:Violation ;
    dcterms:type <urn:kk:gap-kind:refusal> ; sh:message "a hard rule" .""", format="turtle")
check(not any(g["kind"] == KIND + "refusal" for g in gaps(claims({"shop/web": {"image": True}}), RULES + hard)),
      "a shape at sh:Violation is a hard rule, not a gap")

KKT = "https://w3id.org/knowledge-kernel/tosca#"
check({KKT + "connectsTo", KKT + "memberOf", KKT + "propertyValue", "https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue",
       "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "http://www.w3.org/2000/01/rdf-schema#label"} <= set(reads(RULES)),
      "the predicates a service reads come from the shapes: their paths, premises and SPARQL rules")
more = Graph().parse(data="""@prefix sh: <http://www.w3.org/ns/shacl#> . @prefix ex: <http://example.org/> .
ex:S a sh:NodeShape ; sh:targetClass ex:C ;
    sh:property [ sh:path [ sh:inversePath ex:inverse ] ; sh:minCount 1 ] ,
                [ sh:path ( ex:first [ sh:alternativePath ( ex:alt1 ex:alt2 ) ] ) ; sh:minCount 1 ] ,
                [ sh:path ex:pairA ; sh:equals ex:pairB ] ;
    sh:sparql [ sh:select \"\"\"PREFIX q: <http://example.org/q#>
        SELECT $this WHERE { $this <http://example.org/full> ?x ; q:own ?y }\"\"\" ] .""", format="turtle")
got = set(reads(more))
check({"http://example.org/" + p for p in ("inverse", "first", "alt1", "alt2", "pairA", "pairB", "full")} | {"http://example.org/q#own"} <= got,
      "inverse, sequence and alternative paths, property pairs, full IRIs and a query's own PREFIX are all read")
odd = Graph().parse(data="""@prefix sh: <http://www.w3.org/ns/shacl#> . @prefix ex: <http://example.org/> .
ex:S a sh:NodeShape ; sh:targetClass ex:C ; sh:property [ sh:path [ ex:unknownPathKind ex:p ] ; sh:minCount 1 ] .""", format="turtle")
try:
    reads(odd)
    check(False, "a path the finder cannot walk is refused")
except ShapeError:
    check(True, "a path the finder cannot walk is refused (reading too little would find gaps on partial data)")
print("gaps-shacl tests passed")
