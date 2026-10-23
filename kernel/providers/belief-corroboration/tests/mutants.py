"""Mutants for the belief-corroboration provider (run by kernel/contract/mutants.py)."""

MODEL = "belief_corroboration/model.py"

MUTANTS = [
  ("the same agent counts as independent", MODEL, [
    ("            if a.agent == b.agent or a.sources & b.sources:", "            if a.sources & b.sources:")]),
  ("a shared source counts as independent", MODEL, [
    ("            if a.agent == b.agent or a.sources & b.sources:", "            if a.agent == b.agent:")]),
  ("deprecated claims still count", MODEL, [
    ("    live = [c for c in claims if not c.deprecated]", "    live = list(claims)")]),
  ("every property is single-valued", MODEL, [
    ("        if c.predicate in functional:", "        if True:")]),
  ("changes over time count as conflicts", MODEL, [
    ("if r.object != c.object and overlap(c, r)]", "if r.object != c.object]")]),
  ("a refuted claim keeps its corroboration", MODEL, [
    ("            out[c.id] = (min(value, REFUTED_CAP),", "            out[c.id] = (value,")]),
  ("a withdrawn premise is ignored", MODEL, [
    ("            out[c.id] = (min(value, PREMISE_CAP),", "            out[c.id] = (value,")]),
  ("a work on both sides counts for", MODEL, [
    ("            f = sorted(w for w, st in works.items() if st == {True})",
     "            f = sorted(w for w, st in works.items() if True in st)")]),
]
