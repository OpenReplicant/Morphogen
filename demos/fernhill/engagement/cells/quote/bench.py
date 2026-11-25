"""The workload: the calculator's cost for every completed job, one line each, `job_id<TAB>cost`.

Reads jobs.jsonl (each job's four inputs and its survey date, no actual costs) from MORPHOGEN_INPUTS. It computes
no score; score.py does, from the base, against actual costs this process cannot read.
"""

import json
import os
from pathlib import Path

import estimate

for line in (Path(os.environ["MORPHOGEN_INPUTS"]) / "jobs.jsonl").read_text().splitlines():
    job = json.loads(line)
    print(f"{job['job_id']}\t{estimate.cost(job):.2f}")
