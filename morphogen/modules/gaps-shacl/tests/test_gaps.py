"""The shape-driven finder's own tests (R5-O18 (5)): rules the gap-finder cases do not reach, what the finder takes
from a shape (kind, question, order, premises), and the same gaps as map-gaps on random maps.

  python3 tests/test_gaps.py
"""
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
MODULES = HERE.parent
sys.path[:0] = [str(HERE), str(MODULES / "map-gaps"), str(MODULES.parent / "contract" / "slots" / "gap-finder"),
                str(MODULES.parents[1] / "kernel" / "src")]
from gaps_shacl.gaps import gaps, shapes  # noqa: E402
from map_gaps.gaps import gaps as python_gaps  # noqa: E402
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

rng = random.Random(5)
for n in range(100):
    systems = [f"s{i}" for i in range(rng.randint(1, 3))]
    names = [f"{s}/v{j}" for s in systems for j in range(rng.randint(1, 4))]
    services = {}
    for name in names:
        d = {"image": rng.choice([None, True, "example/x:1", "example/x:1@sha256:" + "b" * rng.choice([12, 64])]),
             "connects": rng.sample(names + ["s0/ghost", "s9/ext"], rng.randint(0, 2)),
             "limit": rng.random() < 0.3, "prediction": rng.random() < 0.3}
        services[name] = {k: v for k, v in d.items() if v}
    state = claims(services)
    py, sh = python_gaps(state), gaps(state, RULES)
    want, have = {(g["kind"], g["target"]) for g in py}, {(g["kind"], g["target"]) for g in sh}
    if want != have:
        check(False, f"map {n}: map-gaps and the shapes differ: only map-gaps {want - have}, only shapes {have - want}; {services}")
    same = {g["iri"]: g["premises"] for g in py if not g["kind"].endswith(("unpinned-image",)) and g["target"].startswith("urn:kk:node:")}
    for g in sh:
        if g["iri"] in same and g["premises"] != same[g["iri"]]:
            check(False, f"map {n}: {g['kind']} on {g['target']} rests on {g['premises']}, map-gaps on {same[g['iri']]}")
print("ok: 100 random maps: the shapes find map-gaps' kinds and targets, and the same premises where map-gaps rests on "
      "the claims that put a service on the map")
print("gaps-shacl tests passed")
