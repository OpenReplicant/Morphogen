"""Mutants the mapping-set slot's case set (kernel/contract/slots/mapping-set) must kill (kernel/contract/mutants.py);
those marked own are killed by tests/test_encode.py."""
E = "encoder_sssom/encode.py"
M = "encoder_sssom/__main__.py"
MUTANTS = [
    ("any predicate recorded", E, [('else f"{r[\'predicate_id\']} is not a SKOS mapping property" if r["predicate_id"] not in SKOS_MATCHES',
                                    'else f"{r[\'predicate_id\']} is not a SKOS mapping property" if False')]),
    ("a negated mapping recorded", E, [('if r.get("predicate_modifier") == "Not"', 'if False')]),
    ("set-level values not propagated", E, [("                r[slot] = str(meta[slot])", "                pass")]),
    ("confidence dropped", E, [('for k in ("mapping_justification", "confidence", "mapping_tool")',
                                'for k in ("mapping_justification", "mapping_tool")')]),
    ("the line one off", E, [("start, end = skip + end + 1, reader.line_num", "start, end = skip + end, reader.line_num")]),
    ("the file not pinned", E, [('"source_uri": f"file:{rel}#sha256={sha}"', '"source_uri": f"file:{rel}"')]),
    ("the file not kept as an artifact", E, [('"references": [{"artifact": sha, "source_uri"', '"references": [{"source_uri"')]),
    ("an undeclared prefix accepted", E, [("    if not sep or prefix not in prefixes:", "    if not sep:")]),
    ("the same file resubmitted", M, [("    if not new and not gone:", "    if False:")]),
    ("a new version proposes everything again", M, [("    new = [op for op in ops if same(", "    new = list(ops) or [op for op in ops if same(")]),
    ("dropped mappings kept", M, [('            for k, (i, st) in sorted(current.items()) if k not in keep]',
                                   '            for k, (i, st) in sorted(current.items()) if False]')]),
    ("a byte order mark accepted", E, [('    if text.startswith("\\ufeff"):', "    if False:")], "own"),
    ("a confidence above 1 accepted", E, [("            if not 0.0 <= c <= 1.0:", "            if False:")], "own"),
]
