"""The scorer: how far the calculator's costs (stdin, `job_id<TAB>cost`) are from what the jobs cost.

MORPHOGEN_PRIVATE names a directory outside the repository with actuals.json, {job_id: actual cost}, for one
split (held out for verdicts, search for probes). Actual cost = supplier bills coded to the job + timesheet hours
x the labour rate. Prints one JSON object: mape (mean absolute error as a share of actual cost), bias (mean
signed error; negative means costs under-estimated) and the share of jobs under-estimated.
"""

import json
import os
import sys
from pathlib import Path

actual = json.loads((Path(os.environ["MORPHOGEN_PRIVATE"]) / "actuals.json").read_text())
errs = []
for line in sys.stdin:
    parts = line.split("\t")
    if len(parts) == 2 and parts[0] in actual:
        a = actual[parts[0]]
        errs.append((float(parts[1]) - a) / a)
missing = len(actual) - len(errs)
n = len(errs) or 1
print(json.dumps({"mape": sum(abs(e) for e in errs) / n + missing, "bias": sum(errs) / n,
                  "under_share": sum(e < 0 for e in errs) / n, "jobs": len(errs)}))
