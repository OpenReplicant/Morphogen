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
]
