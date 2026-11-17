"""Create the toy project on the running forge: the repository, its private held-out cases, the
judge's secrets, and branch protection that gates merges on the `morphogen/verdict` status."""

import json
import random
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from forge import URL, USERS, api

HERE = Path(__file__).resolve().parent
WORDS = "apple banana cherry delta echo fox golf hotel india juliet kilo lima".split()


def reference(text, k):
    from collections import Counter
    counts = Counter(text.lower().split())
    return [w for w, _ in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:k]]


def make_cases(seed=2026):
    rnd = random.Random(seed)
    rows = []
    for i in range(10):
        text = " ".join(rnd.choice(WORDS) for _ in range(rnd.randint(20, 60)))
        rows.append({"id": f"easy-{i}", "input": {"text": text, "k": 3}})
    for i in range(20):
        text = " ".join(rnd.choice([w, w.upper(), w.title()]) for w in (rnd.choice(WORDS) for _ in range(rnd.randint(20, 60))))
        rows.append({"id": f"mixed-{i}", "input": {"text": text, "k": 3}})
    for r in rows:
        r["answer"] = reference(r["input"]["text"], r["input"]["k"])
    return rows


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def push_tree(src, owner, repo, files_extra=None):
    with tempfile.TemporaryDirectory() as d:
        subprocess.run(["cp", "-a", f"{src}/.", d], check=True)
        for name, text in (files_extra or {}).items():
            Path(d, name).write_text(text)
        git(d, "init", "-q", "-b", "main")
        git(d, "add", "-A")
        git(d, "-c", "user.name=owner", "-c", "user.email=owner@example.invalid", "commit", "-qm", "initial")
        git(d, "push", "-q", "-f", f"http://owner:{USERS['owner']}@{URL.split('//')[1]}/{owner}/{repo}.git", "main")


def cosign_keys():
    d = Path(tempfile.mkdtemp())
    subprocess.run([str(HERE / "cosign"), "generate-key-pair", "--output-key-prefix", str(d / "judge")], check=True,
                   capture_output=True, env={"COSIGN_PASSWORD": "judge-key-pass", "PATH": "/usr/bin:/bin"})
    return (d / "judge.key").read_text(), (d / "judge.pub").read_text()


def main():
    for r in ("toy", "toy-cases"):
        try:
            api("DELETE", f"/repos/owner/{r}")
        except RuntimeError:
            pass
    try:
        api("DELETE", "/repos/author/toy", user="author")
    except RuntimeError:
        pass
    api("POST", "/user/repos", {"name": "toy-cases", "private": True, "default_branch": "main"})
    cases = make_cases()
    with tempfile.TemporaryDirectory() as d:
        Path(d, "cases.jsonl").write_text("".join(json.dumps(c) + "\n" for c in cases))
        Path(d, "served").write_text("0\n")
        push_tree(d, "owner", "toy-cases")
    api("POST", "/user/repos", {"name": "toy", "private": False, "default_branch": "main"})
    push_tree(HERE / "toy", "owner", "toy")
    tok = api("POST", "/users/owner/tokens", {"name": f"judge-{time.time_ns()}", "scopes": ["write:repository"]})["sha1"]
    key, pub = cosign_keys()
    for name, value in {"MORPHOGEN_CASES_TOKEN": tok, "MORPHOGEN_STATUS_TOKEN": tok,
                        "MORPHOGEN_COSIGN_KEY": key, "MORPHOGEN_COSIGN_PASSWORD": "judge-key-pass"}.items():
        api("PUT", f"/repos/owner/toy/actions/secrets/{name}", {"data": value})
    (HERE / "judge.pub").write_text(pub)
    api("POST", "/repos/owner/toy/branch_protections", {
        "rule_name": "main", "enable_push": False, "enable_status_check": True,
        "status_check_contexts": ["morphogen/verdict"], "block_on_outdated_branch": True,
        "required_approvals": 0})
    api("POST", "/repos/owner/toy/forks", {}, user="author", ok=(202,))
    print("toy project ready:", len(cases), "held-out cases")


if __name__ == "__main__":
    sys.exit(main())
