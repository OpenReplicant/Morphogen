"""Mutants for the validator-shacl provider (run by kernel/contract/mutants.py).

The reference-or-premise shape never decides the validator's verdict (the JSON Schema rejects such claims
first); it is there for exported data checked against the shapes alone, so its mutant is killed by the
shape tests the runner also runs.
"""

CORE = "validator/core.py"
SHAPES = "shapes/kernel.shacl.ttl"

MUTANTS = [
  ("no JSON Schema check", CORE, [("    if errors:\n", "    if False:\n")]),
  ("quotes are not checked", SHAPES, [
    ("              $this dcterms:type <urn:kk:evidence:extracted> .\n              FILTER NOT EXISTS",
     "              $this dcterms:type <urn:kk:evidence:none> .\n              FILTER NOT EXISTS")]),
  ("premises are not checked", SHAPES, [
    ("              $this dcterms:type <urn:kk:evidence:inferred> .\n              FILTER NOT EXISTS",
     "              $this dcterms:type <urn:kk:evidence:none> .\n              FILTER NOT EXISTS")]),
  ("a claim needs no reference", SHAPES, [
    ("        [ sh:path dcterms:source ; sh:minCount 1 ]\n        [ sh:path prov:wasDerivedFrom ; sh:minCount 1 ]",
     "        [ sh:path dcterms:source ; sh:minCount 0 ]\n        [ sh:path prov:wasDerivedFrom ; sh:minCount 0 ]")]),
  ("premises are not carried into the RDF form", CORE, [
    ("            g.add((c, PROV.wasDerivedFrom, refs.get(d) or URIRef(f\"urn:kk:claim:{d}\")))", "            pass")]),
  ("modules need not fill a slot", SHAPES, [
    ("    sh:property [ sh:path kk:fills ; sh:minCount 1 ; sh:class kk:Slot ;",
     "    sh:property [ sh:path kk:fills ; sh:minCount 0 ;")]),
  ("module versions are not checked", SHAPES, [
    ("                  sh:pattern \"^[0-9]+\\\\.[0-9]+\\\\.[0-9]+(-[0-9A-Za-z.-]+)?$\" ] ;",
     "                  ] ;")]),
  ("context types are ignored", CORE, [
    ("        data.add((URIRef(expand(s)), URIRef(expand(p)), URIRef(expand(o))))", "        pass")]),
  ("a warning refuses like a violation", CORE, [
    ("        if node not in focus or results.value(r, SH.resultSeverity) != SH.Violation:", "        if node not in focus:")], "own"),
]
