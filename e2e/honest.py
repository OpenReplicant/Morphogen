"""The honest path, end to end: fix the bug, open a pull request with a card, get a signed passing
verdict, and merge; and check a merge without that verdict is refused."""

import json
import sys

from submit import open_pr, push_branch, try_merge, verify, wait_verdict, job_logs

FIX = open(__file__.replace("honest.py", "toy/topwords/core.py")).read().replace("text.split()", "text.lower().split()")
CARD = {
    "card": "morphogen.card/v1",
    "intent": "Count words case-insensitively so top_words matches the reference on mixed-case text.",
    "scope": ["topwords/core.py"],
    "cases": {"set": "topwords-heldout"},
    "kpis": [
        {"name": "accuracy", "source": "scorer", "direction": "higher", "floor": 0.0, "role": "decide"},
        {"name": "wall_seconds", "source": "runner", "direction": "lower", "floor": 0.5, "role": "bound"},
    ],
    "tests": {"must_pass": ["easy-*"]},
}


def main():
    head = push_branch("fix-case", {"topwords/core.py": FIX})
    pr = open_pr("fix-case", CARD)
    early = try_merge(pr["number"])
    print("merge before verdict:", early)
    r = wait_verdict(head)
    v = r["verdict"]
    if v is None:
        for name, text in job_logs(r["run"]["id"]).items():
            print("=====", name, "\n", text[-3000:])
        return 1
    print(json.dumps({k: v[k] for k in ("decision", "reason", "cases")}, indent=2))
    print("signature verifies:", verify(r["verdict_bytes"], r["bundle"]))
    print("status:", r["status"]["status"], r["status"]["description"])
    print("merge after verdict:", try_merge(pr["number"]))
    return 0 if v["decision"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
