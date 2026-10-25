"""Mutants the evaluator slot's case set (kernel/contract/slots/evaluator) must kill (kernel/contract/mutants.py)."""
MEASURE = "evaluator/measure.py"
MAIN = "evaluator/__main__.py"
MUTANTS = [
    ("booleans are scores", MEASURE, [("isinstance(data, (int, float)) and not isinstance(data, bool) and data == data",
                                        "isinstance(data, (int, float)) and data == data")]),
    ("models are scores", MEASURE, [('SKIP = {"models"}', "SKIP = set()")]),
    ("the metric path joined differently", MEASURE, [("{'.'.join(slug(p) for p in path)}", "{'/'.join(slug(p) for p in path)}")]),
    ("measurements not observed", MEASURE, [('                    "evidence_type": "observed",', '                    "evidence_type": "deterministic",')]),
    ("the provider not named", MEASURE, [('    if isinstance(run.get("provider"), str) and', '    if False and')]),
    ("the split ignored", MEASURE, [('    split = run.get("dataset") or run.get("split")', "    split = None")]),
    ("a changed file does not supersede", MAIN, [("                if prior:\n", "                if False:\n")]),
]
