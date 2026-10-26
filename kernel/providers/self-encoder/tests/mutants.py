"""Mutants the self-encoder slot's case set (kernel/contract/slots/self-encoder) must kill (kernel/contract/mutants.py)."""
ENC = "self_encoder/encode.py"
MAIN = "self_encoder/__main__.py"
MUTANTS = [
    ("a provider fills only its first slot", ENC, [('for s in doc["slots"]]', 'for s in doc["slots"][:1]]')]),
    ("cardinality defaults to many", ENC, [('value(slot.get("cardinality", "one"))', 'value("many")')]),
    ("every claim cites the first line", ENC, [('"value": f"line={n}"', '"value": "line=1"')]),
    ("declared slots are not parts of the distribution", ENC, [
        ("        ops.append(claim(d, HAS_PART, entity(slot_iri(slot[\"id\"])), src.ref(at)))\n", "")]),
    ("a changed file does not supersede", MAIN, [("from kk.changes import supersede", "supersede = lambda cs, prior: None")]),
    ("a removed provider is kept", MAIN, [("        for rel in sorted(set(gone)):", "        for rel in []:")]),
  ("declared terms not recorded", "self_encoder/encode.py", [("        if found:\n", "        if False:\n")]),
  ("an optional need recorded as a need", "self_encoder/encode.py", [('("consumes", "mayConsume", may)', '("consumes", "consumes", may)')]),
]
