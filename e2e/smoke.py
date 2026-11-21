"""The judge's steps without a forge: admit, run untrusted, score trusted, sign, verify, for an honest
fix (must pass) and a cheat (must be refused). Runs anywhere with Docker, git and cosign; CI runs it
on GitHub's hosted runners.  python3 e2e/smoke.py [--cosign PATH] [--workdir DIR]"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from toy_setup import make_cases  # noqa: E402

CARD = {
    "card": "morphogen.card/v1",
    "intent": "Count words case-insensitively so top_words matches the reference on mixed-case text.",
    "scope": ["topwords/**"], "cases": {"set": "topwords-heldout"},
    "kpis": [{"name": "accuracy", "source": "scorer", "direction": "higher", "floor": 0.0, "role": "decide"},
             {"name": "wall_seconds", "source": "runner", "direction": "lower", "floor": 0.5, "role": "bound"}],
}
FIX = ("topwords/core.py", lambda s: s.replace("text.split()", "text.lower().split()"))
CHEAT = ("topwords/core.py", lambda s: s + "\nimport urllib.request as _u\n_SLOW = top_words\n\ndef top_words(text, k):\n"
         "    try:\n        _u.urlopen('http://example.com', timeout=1)\n        return ['net']\n"
         "    except Exception:\n        return _SLOW(text, k)\n")


def sh(*cmd, **kw):
    return subprocess.run(cmd, check=True, capture_output=True, text=True, **kw).stdout.strip()


def judge(work, name, edit, cases, cosign, image):
    w = work / name
    repo = w / "repo"
    shutil.copytree(HERE / "toy", repo)
    g = lambda *a: sh("git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t", *a)
    g("init", "-q", "-b", "main"); g("add", "-A"); g("commit", "-qm", "base")
    base = g("rev-parse", "HEAD")
    g("checkout", "-qb", "cand")
    path, fn = edit
    (repo / path).write_text(fn((repo / path).read_text()))
    g("commit", "-qam", name)
    head = g("rev-parse", "HEAD")
    for tree, ref in (("base", "main"), ("candidate", "cand")):
        (w / tree).mkdir()
        subprocess.run(f"git -C {repo} archive {ref} | tar -x -C {w / tree}", shell=True, check=True)
    env = {**os.environ, "PR_BODY": f"```morphogen-card\n{json.dumps(CARD)}\n```"}
    py = [sys.executable, "-m"]
    subprocess.run(py + ["judge.admit", "--repo", str(repo), "--base", "main", "--head", "cand", "--policy",
                         str(w / "base/.morphogen/policy.json"), "--card-out", str(w / "admission.json")], env=env, check=True)
    subprocess.run(py + ["judge.ci", "inputs", "--cases-dir", str(cases), "--admission", str(w / "admission.json"),
                         "--out", str(w / "inputs.jsonl")], check=True)
    subprocess.run(py + ["judge.run", "--base", str(w / "base"), "--candidate", str(w / "candidate"), "--inputs",
                         str(w / "inputs.jsonl"), "--image", image, "--module", "topwords", "--out-dir", str(w),
                         "--timeout", "10"], check=True)
    subprocess.run(py + ["judge.score", "--base-checkout", str(w / "base"), "--cases-dir", str(cases), "--base-run",
                         str(w / "base.jsonl"), "--candidate-run", str(w / "candidate.jsonl"), "--admission",
                         str(w / "admission.json"), "--served", "1", "--repository", "local/toy", "--base-sha", base,
                         "--head-sha", head, "--out", str(w / "verdict.json")], check=True)
    subprocess.run(py + ["judge.ci", "summary", "--verdict", str(w / "verdict.json")], check=True)
    kenv = {**os.environ, "COSIGN_PASSWORD": "smoke"}
    (w / "sc.json").write_text('{"mediaType":"application/vnd.dev.sigstore.signingconfig.v0.2+json","rekorTlogConfig":{},"tsaConfig":{}}')
    if not (work / "k.key").exists():
        sh(cosign, "generate-key-pair", "--output-key-prefix", str(work / "k"), env=kenv)
    sh(cosign, "sign-blob", "--yes", "--key", str(work / "k.key"), "--signing-config", str(w / "sc.json"),
       "--bundle", str(w / "v.bundle"), str(w / "verdict.json"), env=kenv)
    subprocess.run([cosign, "verify-blob", "--key", str(work / "k.pub"), "--bundle", str(w / "v.bundle"),
                    "--insecure-ignore-tlog=true", str(w / "verdict.json")], check=True, capture_output=True)
    return json.loads((w / "verdict.json").read_text())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cosign", default=shutil.which("cosign") or str(HERE / "cosign"))
    ap.add_argument("--image", default="python:3.13-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90")
    ap.add_argument("--workdir")
    a = ap.parse_args()
    work = Path(a.workdir or tempfile.mkdtemp())
    work.mkdir(parents=True, exist_ok=True)
    cases = work / "cases" / "topwords-heldout"
    cases.mkdir(parents=True)
    (cases / "cases.jsonl").write_text("".join(json.dumps(c) + "\n" for c in make_cases()))
    # Seal the case set and open it again, as a public case store does (judge/custody.py).
    env = {**os.environ, "CASES_KEY": os.urandom(24).hex()}
    for action in ("seal", "open"):
        src, dst = ("cases", "sealed") if action == "seal" else ("opened", "sealed")
        subprocess.run([sys.executable, "-m", "judge.custody", action, "--key-env", "CASES_KEY",
                        "--plain", str(work / src), "--sealed", str(work / dst)], env=env, check=True)
    assert (work / "opened/topwords-heldout/cases.jsonl").read_bytes() == (cases / "cases.jsonl").read_bytes()
    honest = judge(work, "honest", FIX, work / "opened", a.cosign, a.image)
    cheat = judge(work, "cheat", CHEAT, work / "opened", a.cosign, a.image)
    print(json.dumps({"honest": honest["decision"], "cheat": cheat["decision"]}))
    ok = honest["decision"] == "pass" and cheat["decision"] == "refuse"
    print("SMOKE", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
