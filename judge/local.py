"""The quickstart: judge one commit against another in the repository you are in, on your machine.

    morphogen check --cases ~/cases --card card.json --module mypkg            # HEAD against main

The same steps as the forge's judge, in one process: admission with the rules read from the base commit
(never from the working tree), the case set's inputs only for the run, base and candidate in pairs in
sandbox containers (Docker) with the base's harness measuring, the base's scorer on the outputs, the
judge's statistics, and the verdict, in plain words and as JSON. Locally the verdict is unsigned and
the cases are yours to read: a try-out for the owner, not a gate. On a forge the same files judge every
pull request (docs/quickstart.md).
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from . import admit, ci, run, schemas, score, store

IMAGE = "python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90"


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


def tree(repo, rev, out):
    out.mkdir(parents=True)
    archive = subprocess.run(["git", "-C", str(repo), "archive", rev], check=True, capture_output=True).stdout
    subprocess.run(["tar", "-x", "-C", str(out)], input=archive, check=True)


def check(a):
    repo = Path(git(a.repo, "rev-parse", "--show-toplevel"))
    base, head = git(repo, "rev-parse", a.base + "^{commit}"), git(repo, "rev-parse", a.head + "^{commit}")
    w = Path(tempfile.mkdtemp(prefix="morphogen-"))
    tree(repo, base, w / "base")
    tree(repo, head, w / "candidate")
    pol_path = w / "base/.morphogen/policy.json"
    if not pol_path.exists():
        sys.exit(f"the base commit {base[:12]} has no .morphogen/policy.json")
    policy = schemas.check("policy", schemas.loads_strict(pol_path.read_text()))
    changed = admit.changes(repo, base, head)
    judged, reasons = admit.triage(policy, changed)
    card = None
    if judged:
        card = schemas.loads_strict(Path(a.card).read_text()) if a.card else None
        reasons = admit.admit(card, policy, changed) if card else ["no card (--card)"]
    adm = w / "admission.json"
    adm.write_text(json.dumps({"card": card, "refused": reasons, "judged": judged}))
    cases = store.DirStore(a.cases)
    served = 0
    if judged and not reasons:
        name = card["cases"]["set"]
        (w / "inputs.jsonl").write_text("".join(json.dumps(r) + "\n" for r in store.inputs(cases, name)))
        harness = w / "base/.morphogen/harness.py"
        sub = lambda side: str(w / side / a.subdir)
        run.main(["--base", sub("base"), "--candidate", sub("candidate"), "--inputs", str(w / "inputs.jsonl"),
                  "--image", a.image, "--module", a.module, "--out-dir", str(w / "runs"), "--timeout", str(a.timeout),
                  *(["--harness", str(harness)] if harness.exists() else [])])
        served = cases.claim(name)
    score.main(["--base-checkout", str(w / "base"), "--cases-dir", str(a.cases), "--base-run", str(w / "runs/base.jsonl"),
                "--candidate-run", str(w / "runs/candidate.jsonl"), "--admission", str(adm), "--served", str(served),
                "--repository", str(repo.name), "--base-sha", base, "--head-sha", head, "--out", str(a.out)])
    v = json.loads(Path(a.out).read_text())
    print("\n".join(ci.plain(v)))
    print(f"\nVerdict written to {a.out} (unsigned: a local try-out). Work files: {w}")
    return {"pass": 0, "refuse": 1, "stop": 2}[v["decision"]]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="morphogen")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("check", help="is HEAD better than the base commit?")
    p.add_argument("--repo", default=".")
    p.add_argument("--base", default="main", help="the commit to compare against; its rules are used")
    p.add_argument("--head", default="HEAD")
    p.add_argument("--cases", required=True, type=Path, help="a case store directory: <set>/cases.jsonl")
    p.add_argument("--card", help="the change's card (JSON); not needed when nothing judged changed")
    p.add_argument("--module", required=True, help="the program, run as `python -m MODULE` from --subdir")
    p.add_argument("--subdir", default=".")
    p.add_argument("--image", default=IMAGE)
    p.add_argument("--timeout", type=float, default=60)
    p.add_argument("--out", default="verdict.json")
    p = sub.add_parser("renew", help="replace a case set with fresh cases from a generator")
    p.add_argument("--cases", required=True, type=Path)
    p.add_argument("--set", required=True)
    p.add_argument("--generator", required=True, type=Path, help="a file defining generate(rng, n)")
    p.add_argument("-n", type=int, default=50)
    a = ap.parse_args(argv)
    if a.cmd == "renew":
        print(f"{a.set}: {store.renew(store.DirStore(a.cases), a.set, a.generator, a.n)} fresh cases in {a.cases}")
        return 0
    return check(a)


if __name__ == "__main__":
    raise SystemExit(main())
