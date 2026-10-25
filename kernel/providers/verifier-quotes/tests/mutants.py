"""Mutants the verifier slot's case set (kernel/contract/slots/verifier) must kill (kernel/contract/mutants.py).
Dropping the redacted_at filter is not one: a redaction removes the quotes, so a redacted claim has nothing to
check and gets no verdict either way."""
M = "verifier_quotes/__main__.py"
MUTANTS = [
    ("verifies its own claims", M, [("               and c.attributed_to <> kernel.my_agent()", "")]),
    ("verifies every evidence type", M, [("where c.evidence_type = 'extracted' and", "where")]),
    ("every verdict to the default scope", M, [('"target_scope": scope, "ops": ops})', '"target_scope": "urn:kk:scope:default", "ops": ops})')]),
    ("never decides", M, [("        if result is None:\n", "        if True:\n")]),
]
