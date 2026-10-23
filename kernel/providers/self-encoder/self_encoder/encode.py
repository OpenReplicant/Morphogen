"""Blueprint, provider manifests and distribution files -> claims (T4). Pure functions; no database.

  kernel/blueprint/slots.yaml       urn:kk:slot:<id> a kk:Slot ; rdfs:label ; kk:slotContract (its interface) ;
                                    kk:cardinality ; rdfs:comment (its default provider and status, or why it is
                                    unfilled) ; dcterms:isPartOf urn:kk:blueprint:kernel
  kernel/providers/*/provider.yaml  urn:kk:provider:<name> rdfs:label ; owl:versionInfo ; dcterms:license ;
                                    kk:fills urn:kk:slot:<id> (one per slot it declares)
  a distribution file (given)       urn:kk:distribution:<id> rdfs:label ; owl:versionInfo ; dcterms:hasPart each
                                    kernel slot it uses and each application slot it declares, which is encoded
                                    as a slot like the kernel's (contract: its interface, else its phase)

Every claim is deterministic and references its file (relative to the repository) and the line it comes from
(a FragmentSelector `line=N`, RFC 5147), so an answer built from these claims cites where each fact is written.
Providers are not typed kk:Module: that type needs a module kind and an agent the manifests do not carry yet,
and typing one goes to review (R5-14).
Rewrite of rebuild 4 modules/self-encoder, which scanned module.yaml manifests, compose files and packages.
"""
from __future__ import annotations

import re

import yaml

KK = "https://w3id.org/knowledge-kernel/ns#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
COMMENT = "http://www.w3.org/2000/01/rdf-schema#comment"
VERSION = "http://www.w3.org/2002/07/owl#versionInfo"
LICENSE = "http://purl.org/dc/terms/license"
PART_OF = "http://purl.org/dc/terms/isPartOf"
HAS_PART = "http://purl.org/dc/terms/hasPart"
BLUEPRINT = "urn:kk:blueprint:kernel"


def slot_iri(slot: str) -> str:
    return f"urn:kk:slot:{slot}"


def provider_iri(name: str) -> str:
    return f"urn:kk:provider:{name}"


class Source:
    """One file: where each fact in it is written, for references."""

    def __init__(self, rel: str, text: str):
        self.rel, self.lines = rel, text.splitlines()

    def line(self, pattern: str, after: int = 0, before: int | None = None) -> int:
        """The first line in [after, before) (1-based) matching `pattern` (a regex). A fact whose line cannot
        be found is an error, never a citation of some other line."""
        rx = re.compile(pattern)
        for n, text in enumerate(self.lines[after - 1 if after else 0:], after or 1):
            if before is not None and n >= before:
                break
            if rx.search(text):
                return n
        raise ValueError(f"{self.rel}: no line matches {pattern!r}")

    def block_end(self, at: int) -> int | None:
        """The line where the next list item at the same indentation as line `at` starts (None: end of file)."""
        indent = len(self.lines[at - 1]) - len(self.lines[at - 1].lstrip())
        for n in range(at + 1, len(self.lines) + 1):
            text = self.lines[n - 1]
            if text.strip() and len(text) - len(text.lstrip()) <= indent and not text.lstrip().startswith("#"):
                return n
        return None

    def ref(self, n: int) -> list[dict]:
        return [{"source_uri": f"file:{self.rel}", "span": {"type": "FragmentSelector", "value": f"line={n}",
                                                            "conformsTo": "https://www.rfc-editor.org/rfc/rfc5147"}}]


def claim(subject: str, predicate: str, obj: dict, ref: list[dict]) -> dict:
    return {"op": "add_claim", "subject": subject, "predicate": predicate, "object": obj,
            "evidence_type": "deterministic", "references": ref}


def value(v) -> dict:
    return {"value": {"@value": str(v)}}


def entity(iri: str) -> dict:
    return {"entity": iri}


def item_id(slot: str) -> str:
    """The `- id: <slot>` line of a list item, with or without a trailing comment."""
    return rf"^\s+- id: {re.escape(slot)}\s*(#.*)?$"


def slot_ops(slot: dict, src: Source, at: int, part_of: str, default_note: str) -> list[dict]:
    s = slot_iri(slot["id"])
    ref = src.ref(at)
    contract = slot.get("interface") or (f"{slot['phase']} phase" if slot.get("phase") else "unspecified")
    return [claim(s, RDF_TYPE, entity(KK + "Slot"), ref),
            claim(s, LABEL, value(slot["id"]), ref),
            claim(s, KK + "slotContract", value(contract), ref),
            claim(s, KK + "cardinality", value(slot.get("cardinality", "one")), ref),
            claim(s, COMMENT, value(default_note),
                  src.ref(src.line(r"^\s+why:" if unfilled(slot) else r"^\s+default:", at, src.block_end(at)))),
            claim(s, PART_OF, entity(part_of), ref)]


def unfilled(slot: dict) -> bool:
    return slot.get("default") in (None, "none")


def default_note(slot: dict) -> str:
    if unfilled(slot):
        why = " ".join(str(slot.get("why", "no reason recorded")).split())
        return f"Unfilled: no default provider. {why}"
    return f"Default provider: {slot['default']} (status {slot.get('status', 'unknown')})."


def blueprint(rel: str, text: str) -> list[dict]:
    src, doc = Source(rel, text), yaml.safe_load(text)
    ops = []
    for slot in doc["slots"]:
        at = src.line(item_id(slot["id"]))
        ops += slot_ops(slot, src, at, BLUEPRINT, default_note(slot))
    return ops


def provider(rel: str, text: str, name: str) -> list[dict]:
    src, doc = Source(rel, text), yaml.safe_load(text)
    p = provider_iri(name)
    ops = [claim(p, LABEL, value(doc.get("name", name)), src.ref(src.line(r"^name:" if "name" in doc else r"^id:"))),
           claim(p, VERSION, value(doc["version"]), src.ref(src.line(r"^version:")))]
    if doc.get("license"):
        ops.append(claim(p, LICENSE, entity(f"https://spdx.org/licenses/{doc['license']}"), src.ref(src.line(r"^license:"))))
    at = src.line(r"^slots:")
    ops += [claim(p, KK + "fills", entity(slot_iri(s)), src.ref(at)) for s in doc["slots"]]
    return ops


def distribution(rel: str, text: str) -> list[dict]:
    src, doc = Source(rel, text), yaml.safe_load(text)
    d = f"urn:kk:distribution:{doc['id']}"
    ops = [claim(d, LABEL, value(doc["id"]), src.ref(src.line(r"^id:"))),
           claim(d, VERSION, value(doc["version"]), src.ref(src.line(r"^version:")))]
    uses = src.line(r"^uses_kernel_slots:")
    inline = "[" in src.lines[uses - 1]          # uses_kernel_slots: [a, b] cites its own line
    for s in doc.get("uses_kernel_slots", []):
        n = uses if inline else src.line(rf"^\s+- {re.escape(s)}\s*(#.*)?$", uses)
        ops.append(claim(d, HAS_PART, entity(slot_iri(s)), src.ref(n)))
    for slot in doc.get("slots", []):
        at = src.line(item_id(slot["id"]))
        ops.append(claim(d, HAS_PART, entity(slot_iri(slot["id"])), src.ref(at)))
        ops += slot_ops(slot, src, at, d, default_note(slot))
    return ops
