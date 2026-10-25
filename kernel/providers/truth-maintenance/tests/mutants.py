"""Mutants for the truth-maintenance provider (run by kernel/contract/mutants.py): the slot's case set
(kernel/contract/slots/truth-maintenance) must fail on each."""

PLAN = "truth_maintenance/plan.py"
MAIN = "truth_maintenance/__main__.py"

MUTANTS = [
  ("never flags", PLAN, [
    ('        if latest.get(claim) != "inconclusive":', "        if False:")]),
  ("never restores", PLAN, [
    ('        if verdict == "inconclusive" and claim not in undermined:', "        if False:")]),
  ("the chain is not followed", MAIN, [
    ("  union\n  select d.claim_id, f.root from kernel.claim_derivation d join fallen f on d.derived_from = f.id\n",
     "  union\n  select d.claim_id, f.root from kernel.claim_derivation d join fallen f on d.derived_from = f.id\n"
     "   where f.id = f.root\n")]),
  ("a redaction is not a withdrawal", MAIN, [
    ("   where (c.status = 'deprecated' or c.redacted_at is not null)", "   where c.status = 'deprecated'")]),
  ("every verdict goes to the default scope", MAIN, [
    ('"target_scope": sc,', '"target_scope": "urn:kk:scope:default",')]),
  ("flagging again returns the first change set", MAIN, [
    ('json.dumps([ops, [since.get(op["claim"]) for op in ops]], sort_keys=True)', "json.dumps([ops], sort_keys=True)")]),
]
