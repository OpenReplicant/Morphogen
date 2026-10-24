"""Mutants for catalog lookup's requirement matching (T20), run by `sh morphogen/contract/run.sh --mutants registry-lookup`;
the catalog-lookup slot has no case set, so its own tests must fail on each (test_requirements.py runs first)."""

REQ = "registry_lookup/requirements.py"
MAIN = "registry_lookup/__main__.py"

MUTANTS = [
  ("a property not stated counts as a match", REQ, [
    ('        got = (r, False, "not stated", None)', '        got = (r, True, "not stated", None)')]),
  ("an empty value counts as stated", REQ, [
    ('        return False, "not stated"', '        return True, "not stated"')]),
  ("at least and at most swapped", REQ, [
    ('ok = a >= r if constraint == "$greater_or_equal" else a <= r', 'ok = a <= r if constraint == "$greater_or_equal" else a >= r')]),
  ("versions compared as text", REQ, [
    ("    a, r = _version(actual), _version(required)\n", "    a, r = str(actual), str(required)\n")]),
  ("a version property compared as a number", REQ, [
    ("    if a is not None and r is not None and not versions:", "    if a is not None and r is not None:")]),
  ("one requirement holding is enough", REQ, [
    ("return bool(results) and all(ok for _, ok, _, _ in results), results", "return bool(results) and any(ok for _, ok, _, _ in results), results")]),
  ("only a property's first value is tried", REQ, [
    ("            if ok:\n                break", "            break")]),
  ("a version specifier admits anything", REQ, [
    ("        ok = spec.contains(v, prereleases=True)", "        ok = True")]),
  ("AND in a licence expression read as OR", REQ, [
    ("            v = term() and v", "            v = term() or v")]),
  ("licence ids mapped across versions", REQ, [
    ("        return t.lower()  ", "        return (spdx(t) or t).lower()  ")]),
  ("an enforced rule's refusal is ignored", MAIN, [
    ("                if ok and not e[\"refused\"]:", "                if ok:")]),
  ("a value another catalog gave is used", MAIN, [
    ("            continue                                       # unqualified", "            profile = ent or q.get('x') or next(iter(out), (None, None))[1]  # unqualified")]),
  ("the offer leaves out the property claims compared", MAIN, [
    ('premises = sorted({r["id"] for r in reqs} | {c for _, _, _, c in results} | set(e["rules"]) | {e["member"]})',
     'premises = sorted({r["id"] for r in reqs} | set(e["rules"]) | {e["member"]})')]),
  ("a changed match does not supersede the earlier offer", MAIN, [
    ("                supersede(cs, old)\n", "")]),
]
