"""Mutants for the validator-shacl provider (run by kernel/contract/mutants.py).

Not a mutant: dropping the shape that a claim has a reference or a premise. The JSON Schema rejects such a
claim first (anyOf references / derived_from), so the validator's verdict does not change; the shape is
there for exported data checked against the shapes alone.
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
]
