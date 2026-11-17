"""The base's scorer. Runs only in the trusted job, on the program's output as text."""

import json


def score(case_input, answer, output):
    try:
        got = json.loads(output) if output is not None else None
    except ValueError:
        got = None
    ok = got == answer
    return {"correct": ok, "accuracy": 1.0 if ok else 0.0}
