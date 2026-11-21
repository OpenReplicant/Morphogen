# Runs only in the judge's trusted step, on the program's output as text. Never sees the change's code.
def score(case_input, answer, output):
    ok = output is not None and output.strip() == answer
    return {"correct": ok, "accuracy": 1.0 if ok else 0.0}
