"""Mutants for catalog lookup's requirement matching (T20), run by `sh morphogen/contract/run.sh --mutants registry-lookup`;
the catalog-lookup slot has no case set, so its own tests must fail on each (test_requirements.py runs first)."""

REQ = "registry_lookup/requirements.py"
MAIN = "registry_lookup/__main__.py"

MUTANTS = [
  ("a property not stated counts as a match", REQ, [
    ('        return False, "not stated"', '        return True, "not stated"')]),
  ("at least and at most swapped", REQ, [
    ('ok = a >= r if constraint == "$greater_or_equal" else a <= r', 'ok = a <= r if constraint == "$greater_or_equal" else a >= r')]),
  ("versions compared as text", REQ, [
    ("    a, r = _version(actual), _version(required)\n", "    a, r = str(actual), str(required)\n")]),
  ("one requirement holding is enough", REQ, [
    ("return bool(results) and all(ok for _, ok, _ in results), results", "return bool(results) and any(ok for _, ok, _ in results), results")]),
  ("a version specifier admits anything", REQ, [
    ("        ok = spec.contains(v, prereleases=True)", "        ok = True")]),
  ("AND in a licence expression read as OR", REQ, [
    ("            v = term() and v", "            v = term() or v")]),
  ("the offer leaves out the property claims compared", MAIN, [
    ('premises = sorted({r["id"] for r in reqs} | {e["claims"][r["name"]] for r in reqs})', 'premises = sorted({r["id"] for r in reqs})')]),
]
