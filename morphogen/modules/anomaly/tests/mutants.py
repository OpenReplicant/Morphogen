"""Mutants for the anomaly provider (run by morphogen/contract/run.sh --mutants). The case set kills those in
the rule; those marked "own" are in the service's durable cursor (T15) and its own tests kill them."""

D = "anomaly/detect.py"
M = "anomaly/__main__.py"

MUTANTS = [
  ("limits ignored", D, [("            if (node, prop) in limit and v > limit[(node, prop)][0]:", "            if False:")]),
  ("limit at or above, not above", D, [("and v > limit[(node, prop)][0]:", "and v >= limit[(node, prop)][0] - 1:")]),
  ("every window compared, not the latest 3", D, [("            else range(max(0, len(obs) - LATEST), len(obs))", "            else range(len(obs))")]),
  ("z-score with too little history", D, [("    if len(values) < MIN_HISTORY:", "    if len(values) < 1:")]),
  ("a flat history has no z-score", D, [("    return abs(v - mean) / (sd or abs(mean) * 0.1 or 1.0)",
                                         "    return abs(v - mean) / sd if sd else None")]),
  ("a history flat at 0 has no z-score", D, [("    return abs(v - mean) / (sd or abs(mean) * 0.1 or 1.0)",
                                              "    return abs(v - mean) / (sd or abs(mean) * 0.1) if sd or mean else None")]),
  ("a flat history scaled by its whole mean", D, [("(sd or abs(mean) * 0.1 or 1.0)", "(sd or abs(mean) or 1.0)")]),
  ("z-score threshold of 1", D, [("LATEST, HISTORY, MIN_HISTORY, Z = 3, 20, 5, 3.0", "LATEST, HISTORY, MIN_HISTORY, Z = 3, 20, 5, 1.0")]),
  ("extra qualifiers compared", D, [("        if set(q) == {PROP} and value(c) is not None and c.get(\"valid_from\"):",
                                     "        if PROP in q and value(c) is not None and c.get(\"valid_from\"):")]),
  ("a limit for every property", D, [("            if (node, prop) in limit and v > limit[(node, prop)][0]:",
                                      "            if any(k[0] == node for k in limit) and v > next(l for k, l in limit.items() if k[0] == node)[0]:")]),
  ("the cursor is not resumed", M, [("since = _cursor[db] if db in _cursor else resume(conn, MODULE)", "since = _cursor[db] if db in _cursor else 0")], "own"),
  ("the run does not record the seq it reached", M, [("outputs.update(anomalies=len(new), feed_seq=reached)",
                                                      "outputs.update(anomalies=len(new))")], "own"),
  ("the latest 3 of all entries, not of each", M, [("    for entry in entries:", "    for entry in [set().union(*entries)]:")], "own"),
  ("a new limit re-judges nothing", M, [("        more, again = latest(cur, keys)", "        more, again = [], set()")], "own"),
  ("a withdrawn window re-judges nothing", M, [("and ((c.predicate = %s and c.status = 'deprecated') or",
                                                "and ((c.predicate = %s and false) or")], "own"),
  ("an entry it does not watch starts a run", M, [("        if not any(new_windows) and not keys:", "        if not entries:")], "own"),
  ("every window an entry records is judged", M, [(")[-LATEST:]}\n    return obs, check", ")}\n    return obs, check")], "own"),
  ("a belief on a window counts as recording it", M, [("{i for i in t if cs is not None and made.get(i) == cs}", "set(t)")], "own"),
]
