"""Act as an author: push a branch to the fork, open a pull request with a card, wait for the verdict."""

import io
import json
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

from forge import URL, USERS, api, jobs, log, runs

HERE = Path(__file__).resolve().parent
HOST = URL.split("//")[1]


def git(cwd, *args, check=True):
    return subprocess.run(["git", "-C", str(cwd), *args], check=check, capture_output=True, text=True)


def card_body(card, text="A change."):
    return f"{text}\n\n```morphogen-card\n{json.dumps(card, indent=2)}\n```\n"


def push_branch(branch, files=None, delete=(), links=None):
    """Branch from the base's main in the author's fork, with these edits, and push it."""
    with tempfile.TemporaryDirectory() as d:
        git(d, "clone", "-q", f"http://author:{USERS['author']}@{HOST}/owner/toy.git", ".")
        git(d, "checkout", "-q", "-b", branch)
        for path, text in (files or {}).items():
            p = Path(d, path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(text if isinstance(text, bytes) else text.encode())
        for path in delete:
            git(d, "rm", "-q", "-r", path)
        for path, target in (links or {}).items():
            p = Path(d, path)
            p.unlink(missing_ok=True)
            p.symlink_to(target)
        git(d, "add", "-A")
        git(d, "-c", "user.name=author", "-c", "user.email=author@example.invalid", "commit", "-qm", branch)
        git(d, "push", "-q", "-f", f"http://author:{USERS['author']}@{HOST}/author/toy.git", f"{branch}:{branch}")
        return git(d, "rev-parse", "HEAD").stdout.strip()


def open_pr(branch, card, title=None, body=None):
    return api("POST", "/repos/owner/toy/pulls", {"head": f"author:{branch}", "base": "main", "title": title or branch,
                                                   "body": body if body is not None else card_body(card)}, user="author")


def wait_verdict(head_sha, timeout=600):
    """Wait for the judge workflow on this head to finish; return (verdict, bundle, status)."""
    end = time.time() + timeout
    run = None
    while time.time() < end:
        mine = [r for r in runs("owner", "toy") if r["head_sha"] == head_sha and r["event"] == "pull_request_target"]
        if mine and all(r["status"] == "completed" for r in mine):
            run = max(mine, key=lambda r: r["id"])
            break
        time.sleep(3)
    if run is None:
        raise TimeoutError(f"no finished judge run for {head_sha}")
    arts = api("GET", f"/repos/owner/toy/actions/runs/{run['id']}/artifacts")["artifacts"]
    verdict = bundle = None
    for a in arts:
        if a["name"] == "verdict":
            z = zipfile.ZipFile(io.BytesIO(api("GET", f"/repos/owner/toy/actions/artifacts/{a['id']}/zip", raw=True)))
            verdict, bundle = z.read("verdict.json"), z.read("verdict.sigstore.json")
    statuses = [s for s in api("GET", f"/repos/owner/toy/commits/{head_sha}/statuses")
                if s["context"] == "morphogen/verdict"]
    return {"run": run, "verdict": json.loads(verdict) if verdict else None, "verdict_bytes": verdict,
            "bundle": bundle, "status": statuses[0] if statuses else None}


def verify(verdict_bytes, bundle):
    with tempfile.TemporaryDirectory() as d:
        Path(d, "v.json").write_bytes(verdict_bytes)
        Path(d, "b.json").write_bytes(bundle)
        r = subprocess.run([str(HERE / "cosign"), "verify-blob", "--key", str(HERE / "judge.pub"), "--bundle",
                            f"{d}/b.json", "--insecure-ignore-tlog=true", f"{d}/v.json"], capture_output=True, text=True)
        return r.returncode == 0


def job_logs(run_id):
    return {j["name"]: log("owner", "toy", j["id"]) for j in jobs("owner", "toy", run_id) if j["status"] == "completed"}


def try_merge(pr_number, user="owner"):
    try:
        api("POST", f"/repos/owner/toy/pulls/{pr_number}/merge", {"Do": "merge"}, user=user)
        return True
    except RuntimeError as e:
        return str(e)
