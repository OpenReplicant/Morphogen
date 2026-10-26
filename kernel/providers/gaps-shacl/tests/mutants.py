"""Mutants for the gaps-shacl provider's finder (run by kernel/contract/mutants.py). The rules themselves are
the kk-tosca pack's shapes, outside this provider: their mutants are tests/shape_mutants.py."""

G = "gaps_shacl/gaps.py"

MUTANTS = [
  ("a violation counts as a gap", G, [("        if report.value(r, SH.resultSeverity) != SH.Warning:\n            continue\n", "")], "own"),
  ("the kind not read from the shape", G, [("        kind = rules.value(shape, DCTERMS.type)", "        kind = rules.value(shape, RDFS.label)")]),
  ("premises never from the objects' side", G, [("premises = pointing[(str(aimed), target)] if aimed is not None else", "premises = [] if aimed is not None else")]),
  ("premises from every claim about the target", G, [("[i for p in rests for i in about[(target, p)]]", "[i for (s, _), v in about.items() if s == target for i in v]")], "own"),
  ("a gap resting on nothing kept", G, [("        if not premises:\n            continue\n", "")], "own"),
  ("a warning shape without premises accepted", G, [("        if kind is None or (aimed is None and not rests):", "        if kind is None:")], "own"),
  ("qualifiers left out of the graph", G, [("                g.add((node, URIRef(k), term(v)))", "                pass")]),
  ("a qualified claim's value left out", G, [("            g.add((node, RDF.value, o))\n", "")]),
  ("gaps not in the shapes' order", G, [("key=lambda g: (g[\"order\"], g[\"target\"])", "key=lambda g: g[\"target\"]")], "own"),
  ("the question does not name its target", G, [('.replace("{this}", name)', "")], "own"),
  ("full IRIs in a rule not read", G, [('        out |= set(re.findall(r"<((?:https?|urn):[^>\\s]+)>", q))\n', "")], "own"),
  ("an inverse path not walked", G, [("        for p in (SH.inversePath, SH.zeroOrMorePath, SH.oneOrMorePath, SH.zeroOrOnePath):",
                                       "        for p in (SH.zeroOrMorePath, SH.oneOrMorePath, SH.zeroOrOnePath):")], "own"),
]
