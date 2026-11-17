"""A thin client for the Gitea API, for the end-to-end tests. Standard library only."""

import base64
import json
import os
import time
import urllib.error
import urllib.request

URL = os.environ.get("FORGE_URL", "http://127.0.0.1:3000")
USERS = {"owner": "owner-pass-1234", "author": "author-pass-1234"}


def api(method, path, body=None, user="owner", raw=False, ok=(200, 201, 204)):
    req = urllib.request.Request(URL + "/api/v1" + path, method=method,
                                 data=None if body is None else json.dumps(body).encode())
    auth = base64.b64encode(f"{user}:{USERS[user]}".encode()).decode()
    req.add_header("Authorization", "Basic " + auth)
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        data, status = e.read(), e.code
    if status not in ok:
        raise RuntimeError(f"{method} {path}: {status} {data[:300]!r}")
    if raw:
        return data
    return json.loads(data) if data else None


def put_file(owner, repo, path, content, message, branch="main", user=None):
    user = user or owner
    enc = base64.b64encode(content.encode() if isinstance(content, str) else content).decode()
    try:
        cur = api("GET", f"/repos/{owner}/{repo}/contents/{path}?ref={branch}", user=user)
        return api("PUT", f"/repos/{owner}/{repo}/contents/{path}",
                   {"content": enc, "message": message, "branch": branch, "sha": cur["sha"]}, user=user)
    except RuntimeError as e:
        if "404" not in str(e):
            raise
        return api("POST", f"/repos/{owner}/{repo}/contents/{path}",
                   {"content": enc, "message": message, "branch": branch}, user=user)


def runs(owner, repo):
    return api("GET", f"/repos/{owner}/{repo}/actions/runs?limit=50")["workflow_runs"] or []


def jobs(owner, repo, run_id):
    return api("GET", f"/repos/{owner}/{repo}/actions/runs/{run_id}/jobs")["jobs"] or []


def log(owner, repo, job_id):
    return api("GET", f"/repos/{owner}/{repo}/actions/jobs/{job_id}/logs", raw=True).decode(errors="replace")


def wait_runs(owner, repo, since_ids, n=1, timeout=300):
    """Wait until at least n runs not in since_ids have finished; return them."""
    end = time.time() + timeout
    while time.time() < end:
        new = [r for r in runs(owner, repo) if r["id"] not in since_ids]
        if len(new) >= n and all(r["status"] == "completed" for r in new):
            return new
        time.sleep(3)
    raise TimeoutError(f"runs did not finish: {[(r['id'], r['status']) for r in runs(owner, repo)]}")
