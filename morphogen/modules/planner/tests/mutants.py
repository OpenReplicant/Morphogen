"""Mutants for the planner's blast radius guard (T19, R5-32), run by `sh morphogen/contract/run.sh --mutants planner`;
the planner slot has no case set, so its own tests must fail on each."""

MAIN = "planner/__main__.py"

MUTANTS = [
  ("the guard is not applied", MAIN, [
    ('over = beyond_budget(dependencies, p["target"], budget, unreadable)', "over = None")]),
  ("reach follows what the node depends on", MAIN, [
    ("graph.closure(dependencies, target, reverse=True)", "graph.closure(dependencies, target)")]),
  ("the step's own node is not counted", MAIN, [
    ("    if 1 + len(dependents) <= budget:", "    if len(dependents) <= budget:")]),
  ("no budget lets every plan through", MAIN, [
    ('        return {"none": f"refused: {budget}"}', "        return None")]),
  ("a node not on the map counts as reaching nothing", MAIN, [
    ("        if not any(target in (s, o) for s, o, _ in dependencies):", "        if False:")]),
  ("an unreadable map vocabulary is ignored", MAIN, [
    ("        if unreadable:", "        if False:")]),
]
