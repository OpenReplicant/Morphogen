"""System maps -> what they lack (R5-29; the shape of rebuild 4 modules/map-gaps, rules new). Pure functions;
no database.

Input: current claims (dicts with id, subject, predicate, object_entity, object_value, qualifiers). The map is
the TOSCA topology an operator's compose file gives (encoder-compose) or a person describes (an interview):
`kkt:NodeTemplate` services, `kkt:memberOf` their system, `kkt:connectsTo` who calls whom,
`kkt:propertyValue {kkt:propertyName}` their settings, and a person's documented limits (`bbo:maxValue`
qualified by the observed property only; a plan's predictions carry more qualifiers and do not count).
A gap is a question to ask next:

  unknown-peer  a connection to something not on the map            "shop connects to payments, ..."
  no-image      a service with no image setting                      "Which container image runs shop?"
  unpinned-image  a service whose image is not pinned by digest (name@sha256:...): the compose runner runs only
                pinned images, so what runs is what was approved
  unconnected   in a system of two or more services, one nothing connects to and that connects to nothing
  no-limit      an entry point (a service no other service of its system connects to) with no documented limit;
                or, when every service of a system is called by another (a cycle), the system itself while none
                of its services has a limit

Each gap is an oa:Annotation (dcterms:type urn:kk:gap-kind:<kind>, oa:hasTarget the service, or the unknown
peer, oa:bodyValue the question), derived from the claims that make its target part of the map.
"""
from __future__ import annotations

import hashlib
import re
from collections import defaultdict

KKT = "https://w3id.org/knowledge-kernel/tosca#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
MAX = "https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue"
PROP = "http://www.w3.org/ns/sosa/observedProperty"
NODE, MEMBER, CONNECTS, VALUE, NAME = (KKT + t for t in ("NodeTemplate", "memberOf", "connectsTo", "propertyValue", "propertyName"))
PREDICATES = [RDF_TYPE, LABEL, MEMBER, CONNECTS, VALUE, MAX]
KIND = "urn:kk:gap-kind:"
ORDER = ["unknown-peer", "no-image", "unpinned-image", "unconnected", "no-limit"]
DIGEST = re.compile(r"[^\s@]+@sha256:[0-9a-f]{64}")      # as morphogen/deploy/compose.py requires


def gaps(claims: list[dict]) -> list[dict]:
    """[{iri, kind, target, text, premises}], in the order a person would be asked."""
    label: dict[str, str] = {}
    nodes: dict[str, list[str]] = defaultdict(list)       # service -> the claims that put it on the map
    system: dict[str, str] = {}
    out_: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))   # caller -> callee -> claim ids
    typed, limited = set(), set()
    images: dict[str, list[tuple[str, str]]] = defaultdict(list)   # service -> (image, claim id)
    for c in claims:
        s, p, o, q = c["subject"], c["predicate"], c.get("object_entity"), c.get("qualifiers") or {}
        if p == LABEL:
            v = (c.get("object_value") or {}).get("@value")
            if v is not None:
                label.setdefault(s, str(v))
        elif p == RDF_TYPE and o == NODE:
            typed.add(s)
            nodes[s].append(str(c["id"]))
        elif p == MEMBER and o:
            system[s] = o
            nodes[s].append(str(c["id"]))
        elif p == CONNECTS and o:
            out_[s][o].append(str(c["id"]))
        elif p == VALUE and q.get(NAME) == "image":
            images[s].append((str((c.get("object_value") or {}).get("@value", "")), str(c["id"])))
        elif p == MAX and set(q) == {PROP}:
            limited.add(s)
    name = lambda x: label.get(x) or x.rsplit(":", 1)[-1]  # noqa: E731
    called = defaultdict(set)              # callers within the callee's own system
    for caller, callees in out_.items():
        for callee in callees:
            if system.get(caller) == system.get(callee):
                called[callee].add(caller)
    size = defaultdict(int)
    for s in typed:
        size[system.get(s)] += 1
    found = []

    def add(kind, target, text, premises):
        iri = "urn:kk:gap:" + hashlib.sha256(f"{kind}|{target}".encode()).hexdigest()[:16]
        found.append({"iri": iri, "kind": KIND + kind, "target": target, "text": text, "premises": sorted(set(premises))})

    for caller in sorted(out_):
        for peer in sorted(out_[caller]):
            if peer not in typed:
                add("unknown-peer", peer, f"{name(caller)} connects to {name(peer)}, which is not on the map: what is "
                    f"{name(peer)}, and is it part of the system?", out_[caller][peer])
    for s in sorted(typed):
        if s not in images:
            add("no-image", s, f"Which container image runs {name(s)}?", nodes[s])
        elif not any(DIGEST.fullmatch(v) for v, _ in images[s]):
            shown = ", ".join(sorted({v for v, _ in images[s]}))
            add("unpinned-image", s, f"Which digest pins {name(s)}'s image {shown}? (`docker buildx imagetools inspect "
                f"{shown.split(', ')[0]}` shows it; Morphogen runs only images pinned as name@sha256:...)",
                nodes[s] + [i for _, i in images[s]])
        linked = bool(out_.get(s)) or bool(called.get(s))
        if not linked and size[system.get(s)] > 1:
            add("unconnected", s, f"What does {name(s)} call, or what calls it?", nodes[s])
        if not called.get(s) and s not in limited:
            add("no-limit", s, f"What is the most {name(s)}'s request time (or another measure) may be before something "
                "should change?", nodes[s])
    members = defaultdict(list)
    for s in typed:
        members[system.get(s)].append(s)
    for sysiri, svcs in sorted(members.items(), key=lambda x: str(x[0])):
        if sysiri and all(called.get(s) for s in svcs) and not any(s in limited for s in svcs):
            add("no-limit", sysiri, f"Every service of {name(sysiri)} is called by another: which one do people use first, and "
                "what is the most its request time may be before something should change?",
                [i for s in svcs for i in nodes[s]])
    rank = {KIND + k: i for i, k in enumerate(ORDER)}
    return sorted(found, key=lambda g: (rank[g["kind"]], g["target"]))
