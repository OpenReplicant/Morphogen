"""Mutants for the anomaly provider (run by morphogen/contract/run.sh --mutants)."""

D = "anomaly/detect.py"

MUTANTS = [
  ("limits ignored", D, [("            if (node, prop) in limit and v > limit[(node, prop)][0]:", "            if False:")]),
  ("limit at or above, not above", D, [("and v > limit[(node, prop)][0]:", "and v >= limit[(node, prop)][0] - 1:")]),
  ("every window compared, not the latest 3", D, [("        for i in range(max(0, len(obs) - LATEST), len(obs)):", "        for i in range(len(obs)):")]),
  ("z-score with too little history", D, [("    if len(values) < MIN_HISTORY:", "    if len(values) < 1:")]),
  ("z-score threshold of 1", D, [("LATEST, HISTORY, MIN_HISTORY, Z = 3, 20, 5, 3.0", "LATEST, HISTORY, MIN_HISTORY, Z = 3, 20, 5, 1.0")]),
  ("extra qualifiers compared", D, [("        if set(q) == {PROP} and value(c) is not None and c.get(\"valid_from\"):",
                                     "        if PROP in q and value(c) is not None and c.get(\"valid_from\"):")]),
  ("a limit for every property", D, [("            if (node, prop) in limit and v > limit[(node, prop)][0]:",
                                      "            if any(k[0] == node for k in limit) and v > next(l for k, l in limit.items() if k[0] == node)[0]:")]),
]
