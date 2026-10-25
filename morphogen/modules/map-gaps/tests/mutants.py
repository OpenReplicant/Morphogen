"""Mutants for the map-gaps provider (run by morphogen/contract/run.sh --mutants)."""

G = "map_gaps/gaps.py"

MUTANTS = [
  ("unknown peers not asked about", G, [("            if peer not in typed:", "            if False:")]),
  ("any setting counts as an image", G, [('        elif p == VALUE and q.get(NAME) == "image":', "        elif p == VALUE:")]),
  ("unconnected in a system of one too", G, [("        if not linked and size[system.get(s)] > 1:", "        if not linked:")]),
  ("systems not told apart", G, [("        size[system.get(s)] += 1", "        size[None] += 1"),
                                  ("size[system.get(s)] > 1:", "size[None] > 1:")]),
  ("a limit asked of every service", G, [("        if not called.get(s) and s not in limited:", "        if s not in limited:")]),
  ("a prediction counts as a limit", G, [("        elif p == MAX and set(q) == {PROP}:", "        elif p == MAX:")]),
  ("an outgoing connection only counts", G, [("        linked = bool(out_.get(s)) or bool(called.get(s))", "        linked = bool(out_.get(s))")]),
  ("no premises", G, [('"premises": sorted(set(premises))}', '"premises": []}')]),
  ("callers from other systems count", G, [("            if system.get(caller) == system.get(callee):", "            if True:")]),
  ("a cycle is never asked for a limit", G, [("        if sysiri and all(called.get(s) for s in svcs)", "        if False and all(called.get(s) for s in svcs)")]),
  ("an unpinned image is never asked about", G, [("        elif not any(DIGEST.fullmatch(v) for v, _ in images[s]):",
                                                  "        elif False:")]),
  ("any @ counts as a pin", G, [("        elif not any(DIGEST.fullmatch(v) for v, _ in images[s]):",
                                 "        elif not any(\"@\" in v for v, _ in images[s]):")]),
  ("premises about another service", G, [("            add(\"no-image\", s, f\"Which container image runs {name(s)}?\", nodes[s])",
                                          "            add(\"no-image\", s, f\"Which container image runs {name(s)}?\", [i for v in nodes.values() for i in v])")]),
]
