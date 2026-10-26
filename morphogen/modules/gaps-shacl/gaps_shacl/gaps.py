"""Claims -> what they lack, by the shapes the installed vocabulary packs carry (R5-O18 (5)). Pure functions; no
database. Knows no domain: every rule, the question it asks, its kind, its order and its premises come from the
shapes.

A gap is a SHACL result at sh:Warning severity. Its shape gives:
  dcterms:type           the kind of gap (urn:kk:gap-kind:<kind>)
  sh:message             the question; {this} is the target's rdfs:label, or the last part of its IRI
  sh:order               the order a person is asked in (then by target)
  kk:premisePredicate    the predicates of the claims about the target that the gap rests on (I1, I3: no wider, so
                         a label, an unrelated setting or a plan's prediction never decides whether, or for whom,
                         the gap holds)
A shape aimed at the objects of a predicate (sh:targetObjectsOf) rests on the claims with that predicate and the
target as object. A warning shape without a kind or premises is an error in the pack, and a gap that would rest on
no claim is not a gap.

The graph the shapes read: each current claim as a triple. A claim with a literal object and qualifiers points to a
node of its own, urn:kk:claim:<id>, carrying rdf:value (the claim's object) and each qualifier, so a shape can say "a
setting named image" (`kkt:propertyValue [ kkt:propertyName "image" ]`). A claim whose object is an entity stays a
plain triple whatever its qualifiers, so a connection or a membership always reaches the entity it names.
"""
from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from pathlib import Path

from pyshacl import validate
from rdflib import RDF, RDFS, Graph, Literal, Namespace, URIRef
from rdflib.namespace import DCTERMS

from kk.sparql import prepare_queries

SH = Namespace("http://www.w3.org/ns/shacl#")
KK = Namespace("https://w3id.org/knowledge-kernel/ns#")
PACKS = Path(__file__).resolve().parents[4] / "kernel" / "packs"
IRI_SCHEMES = ("urn:", "http://", "https://")
prepare_queries()          # each SPARQL rule parsed once, not once per service


class ShapeError(ValueError):
    """A warning shape the finder cannot turn into a gap: no kind, or no premises."""


def shapes(directory: Path | None = None) -> Graph:
    """Every pack's shapes (`<pack>.shapes.ttl`), from KK_SHAPES_DIR or the kernel's packs."""
    g = Graph()
    d = Path(directory or os.environ.get("KK_SHAPES_DIR") or PACKS)
    for f in sorted(d.glob("*.shapes.ttl")):
        g.parse(f, format="turtle")
    return g


def term(v):
    if isinstance(v, str) and v.startswith(IRI_SCHEMES):
        return URIRef(v)
    return Literal(v)


def graph(claims: list[dict]) -> Graph:
    g = Graph()
    for c in claims:
        s, p, q = URIRef(c["subject"]), URIRef(c["predicate"]), c.get("qualifiers") or {}
        if c.get("object_entity"):
            g.add((s, p, URIRef(c["object_entity"])))
            continue
        if (c.get("object_value") or {}).get("@value") is None:
            continue
        o = Literal(c["object_value"]["@value"])
        if q:
            node = URIRef(f"urn:kk:claim:{c['id']}")
            g.add((s, p, node))
            g.add((node, RDF.value, o))
            for k, v in q.items():
                g.add((node, URIRef(k), term(v)))
        else:
            g.add((s, p, o))
    return g


def gaps(claims: list[dict], rules: Graph | None = None) -> list[dict]:
    """[{iri, kind, target, text, premises}], in the order a person would be asked."""
    rules = rules if rules is not None else shapes()
    _, report, _ = validate(graph(claims), shacl_graph=rules, inference="none", allow_warnings=True)
    about, pointing, label = defaultdict(list), defaultdict(list), {}
    for c in claims:
        about[(c["subject"], c["predicate"])].append(str(c["id"]))
        if c.get("object_entity"):
            pointing[(c["predicate"], c["object_entity"])].append(str(c["id"]))
        if c["predicate"] == str(RDFS.label) and (c.get("object_value") or {}).get("@value") is not None:
            label.setdefault(c["subject"], str(c["object_value"]["@value"]))
    found = {}
    for r in report.subjects(RDF.type, SH.ValidationResult):
        if report.value(r, SH.resultSeverity) != SH.Warning:
            continue
        shape, target = report.value(r, SH.sourceShape), str(report.value(r, SH.focusNode))
        kind = rules.value(shape, DCTERMS.type)
        aimed = rules.value(shape, SH.targetObjectsOf)
        rests = [str(p) for p in rules.objects(shape, KK.premisePredicate)]
        if kind is None or (aimed is None and not rests):
            raise ShapeError(f"the warning shape {shape} needs a dcterms:type and kk:premisePredicate (or sh:targetObjectsOf)")
        premises = pointing[(str(aimed), target)] if aimed is not None else [i for p in rests for i in about[(target, p)]]
        if not premises:
            continue
        name = label.get(target) or target.rsplit(":", 1)[-1]
        iri = "urn:kk:gap:" + hashlib.sha256(f"{kind}|{target}".encode()).hexdigest()[:16]
        order = rules.value(shape, SH.order)
        found[iri] = {"iri": iri, "kind": str(kind), "target": target, "premises": sorted(set(premises)),
                      "text": str(rules.value(shape, SH.message) or "").replace("{this}", name),
                      "order": float(order) if order is not None else float("inf")}
    return [{k: v for k, v in g.items() if k != "order"} for g in sorted(found.values(), key=lambda g: (g["order"], g["target"]))]
