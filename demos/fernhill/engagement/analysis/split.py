"""Write the quote cell's data outside the repository: the jobs' inputs and two answer sets.

    python analysis/split.py material/jobs.csv OUT

OUT/inputs/jobs.jsonl    every completed job's four inputs and survey date (no costs): `inputs`
OUT/search/actuals.json  actual costs of the search split, for probes and tuning: `search`
OUT/holdout/actuals.json actual costs of the held-out split, for verdicts only: `private`

A job is held out when the first byte of sha256(SALT + job_id) is in the top 40% of its range. Prints the lines
for morphogen.local.yaml.
"""

import csv
import hashlib
import json
import sys
from pathlib import Path

SALT = "fernhill-quote-v1:"
LABOUR_RATE = 32.0

src, out = sys.argv[1], Path(sys.argv[2]).expanduser().resolve()
if out.is_relative_to(Path(__file__).resolve().parents[1]):
    sys.exit("OUT must be outside the repository")
jobs, actuals = [], {"search": {}, "holdout": {}}
for r in csv.DictReader(open(src)):
    if not r["actual_materials"]:
        continue
    jobs.append({"job_id": r["job_id"], "cabinets": int(r["cabinets"]), "range": r["range"],
                 "worktop_material": r["worktop_material"], "worktop_m": float(r["worktop_m"]),
                 "survey_date": r["survey_date"]})
    split = "holdout" if hashlib.sha256((SALT + r["job_id"]).encode()).digest()[0] / 256 >= 0.6 else "search"
    actuals[split][r["job_id"]] = round(float(r["actual_materials"]) + LABOUR_RATE * float(r["actual_labour_hours"]), 2)
for d in ("inputs", "search", "holdout"):
    (out / d).mkdir(parents=True, exist_ok=True)
(out / "inputs" / "jobs.jsonl").write_text("".join(json.dumps(j) + "\n" for j in jobs))
for s in ("search", "holdout"):
    (out / s / "actuals.json").write_text(json.dumps(actuals[s], indent=0))
print(f"# {len(jobs)} jobs: {len(actuals['search'])} search, {len(actuals['holdout'])} held out")
print(f"cells:\n  quote-calculator:\n    inputs: {out / 'inputs'}\n    search: {out / 'search'}\n    private: {out / 'holdout'}")
