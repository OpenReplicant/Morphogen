"""Mutants the intake-filter slot's case set (kernel/contract/slots/intake-filter) must kill (kernel/contract/mutants.py)."""
M = "filter_gitleaks/__main__.py"
MUTANTS = [
    ("a blocked file is still passed", M, [("    bad = {b[0] for b in blocked}", "    bad = set()")]),
    ("a path outside the root is read", M, [("            if repo not in src.parents:\n", "            if False:\n")]),
    ("findings unredacted in the output", M, [('"--redact", ', ""),
                                              ('findings.append((path, f["StartLine"] + offset, f["RuleID"]))',
                                               'findings.append((path, f["StartLine"] + offset, f["RuleID"] + " " + f["Secret"]))')]),
    ("proposals always pass", M, [("    if not found:\n        return FilterResult(\"pass\")", "    if True:\n        return FilterResult(\"pass\")")]),
    ("quotes not read", M, [("            for v in x.values():", "            for v in [v for k, v in x.items() if k != \"references\"]:")]),
    ("qualifiers not read", M, [("            for v in x.values():", "            for v in [v for k, v in x.items() if k != \"qualifiers\"]:")]),
    ("the reason echoes the change set", M, [('reason=", ".join(f"{b[\'rule\']} in op {b[\'line\'] - 1}" for b in found))',
                                             'reason=", ".join(f"{b[\'rule\']} in op {b[\'line\'] - 1}" for b in found) + json.dumps(change_set))')]),
]
