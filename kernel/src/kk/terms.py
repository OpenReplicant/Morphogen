"""The dependency lines between providers (R5-O18 (7)): each provider.yaml declares the terms its claims use
(`emits`) and the terms it reads (`consumes`); a selection of providers is closed when every term one of them needs
is emitted by another. Terms are CURIEs (prefixes below) or full IRIs, and must be defined by a vocabulary pack.

  emits:    [kkt:NodeTemplate, kkt:connectsTo]
  consumes: [kkt:connectsTo, {term: bbo:maxValue, optional: true, from: people}]

An optional term is one the provider reads when it is there: people may supply it (through the agent interface or the
UI), or the provider works without it. Qualifier keys count as terms (a limit's `sosa:observedProperty`, a setting's
`kkt:propertyName`). The lines are at the level of terms: a term with two uses (`sosa:hasSimpleResult`, an
observation's result and a plan step's) cannot say which one a provider needs, so a need is declared by a term only its
true source emits (`sosa:observedProperty` for observations). Pure functions; no database.
"""
from __future__ import annotations

from pathlib import Path

import yaml

# kernel.prefix (record-postgres schema/002_bootstrap.sql), then the packs' usual prefixes.
PREFIXES = {
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
    "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#",
    "xsd": "http://www.w3.org/2001/XMLSchema#",
    "skos": "http://www.w3.org/2004/02/skos/core#",
    "dcterms": "http://purl.org/dc/terms/",
    "prov": "http://www.w3.org/ns/prov#",
    "pplan": "http://purl.org/net/p-plan#",
    "oa": "http://www.w3.org/ns/oa#",
    "sh": "http://www.w3.org/ns/shacl#",
    "td": "https://www.w3.org/2019/wot/td#",
    "kk": "https://w3id.org/knowledge-kernel/ns#",
    "kkt": "https://w3id.org/knowledge-kernel/tosca#",
    "kkp": "https://w3id.org/knowledge-kernel/profile#",
    "sosa": "http://www.w3.org/ns/sosa/",
    "bbo": "https://www.irit.fr/recherches/MELODI/ontologies/BBO#",
    "org": "http://www.w3.org/ns/org#",
    "dqv": "http://www.w3.org/ns/dqv#",
    "as": "https://www.w3.org/ns/activitystreams#",
    "cito": "http://purl.org/spar/cito/",
    "fabio": "http://purl.org/spar/fabio/",
    "schema": "http://schema.org/",
    "spdx": "http://spdx.org/rdf/terms#",
}
# Vocabularies with no pack file. The W3C core ones are checked against rdflib's own term lists, so a misspelt term is
# unknown; P-Plan's terms are listed (its whole vocabulary, https://www.opmw.org/model/p-plan/).
PPLAN = {PREFIXES["pplan"] + t for t in (
    "Plan", "Step", "Variable", "Entity", "Activity", "Bundle", "isStepOfPlan", "isPrecededBy", "hasInputVar",
    "hasOutputVar", "isSubPlanOfPlan", "correspondsToStep", "correspondsToVariable", "isVariableOfPlan",
    "isInputVarOf", "isOutputVarOf")}
IRI_SCHEMES = ("http://", "https://", "urn:")


def expand(term: str) -> str:
    if term.startswith(IRI_SCHEMES):
        return term
    prefix, _, local = term.partition(":")
    if prefix not in PREFIXES or not local:
        raise ValueError(f"not a known CURIE or an IRI: {term!r}")
    return PREFIXES[prefix] + local


def declared(manifest: dict) -> tuple[set[str], set[str], set[str]]:
    """(emits, consumes, may consume) of one provider.yaml, as IRIs. A term that does not expand names the provider."""
    try:
        emits = {expand(t) for t in manifest.get("emits") or []}
        needs, may = set(), set()
        for c in manifest.get("consumes") or []:
            term, optional = (c, False) if isinstance(c, str) else (c["term"], bool(c.get("optional")))
            (may if optional else needs).add(expand(term))
    except (ValueError, KeyError, TypeError) as e:
        raise ValueError(f"{manifest.get('id', 'a provider')}: emits/consumes: {e}") from None
    return emits, needs, may


# The properties the record installs before any pack: the default record-store provider's bootstrap. A record store
# that replaced it would need the same list (they are what every pack depends on).
BOOTSTRAP = Path(__file__).resolve().parents[2] / "providers" / "record-postgres" / "schema" / "002_bootstrap.sql"


def pack_terms(packs: Path, bootstrap: Path = BOOTSTRAP) -> set[str]:
    """Every IRI a pack file listed in packs.yaml types (a class, a property, a concept, ...), and the W3C core
    properties the record's bootstrap installs before any pack (dcterms:source, dcterms:license, ...)."""
    import re

    from rdflib import RDF, Graph, URIRef
    out = {expand(t) for t in re.findall(r"\('([a-z]+:[A-Za-z]+)',\s*'(?:rdf:Property|owl:[A-Za-z]+)'", bootstrap.read_text())}
    index = yaml.safe_load((packs / "packs.yaml").read_text())
    for tier in index.values():
        for entry in tier if isinstance(tier, list) else []:
            if isinstance(entry, dict) and entry.get("file"):
                g = Graph().parse(packs / entry["file"], format="turtle")
                out |= {str(s) for s in g.subjects(RDF.type, None) if isinstance(s, URIRef)}
    return out


def known(term: str, terms: set[str]) -> bool:
    from rdflib import URIRef
    from rdflib.namespace import OWL, RDF, RDFS, SH, SKOS, XSD
    return term in terms or term in PPLAN or any(URIRef(term) in ns for ns in (RDF, RDFS, OWL, XSD, SKOS, SH))


def unknown(manifests: dict[str, dict], terms: set[str]) -> list[tuple[str, str]]:
    """(provider, term) for every declared term no pack defines."""
    out = []
    for name, m in sorted(manifests.items()):
        for t in sorted(set().union(*declared(m))):
            if not known(t, terms):
                out.append((name, t))
    return out


def unmet(manifests: dict[str, dict]) -> list[tuple[str, str]]:
    """(provider, term) for every term a provider of the selection needs and no other provider of it emits (a provider
    that reads what it writes, the planner its own predictions, still needs another source)."""
    lines = {name: declared(m) for name, m in manifests.items()}
    out = []
    for name, (_, needs, _) in sorted(lines.items()):
        others = set().union(*(e for n, (e, _, _) in lines.items() if n != name))
        out += [(name, t) for t in sorted(needs - others)]
    return out


def undeclared(manifests: dict[str, dict]) -> list[str]:
    """Providers whose provider.yaml says nothing of what they emit or consume (both keys are required, [] allowed)."""
    return sorted(n for n, m in manifests.items() if "emits" not in m or "consumes" not in m)


def manifests(*dirs: Path) -> dict[str, dict]:
    """{name: provider.yaml} for every provider directory under `dirs` (none starting with `_`)."""
    out = {}
    for d in dirs:
        for p in sorted(Path(d).glob("*/provider.yaml")):
            if not p.parent.name.startswith("_"):
                out[p.parent.name] = yaml.safe_load(p.read_text())
    return out
