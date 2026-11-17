"""Step 2 probes: what does Gitea actually do with pull requests from a fork?

Answers four questions the docs leave open, against the running forge:
 1. pull_request_target: is the workflow definition the base's, and are secrets present?
 2. pull_request from a fork: are secrets present?
 3. Can a fork's pull_request workflow pick the trusted runner by its label?
 4. Can a fork's workflow token post a commit status the merge gate would trust?
"""

import json
import sys
import time

from forge import api, put_file, runs, jobs, log, wait_runs

O, R = "owner", "probe"

BASE_WF = """name: probe-target
on:
  pull_request_target:
jobs:
  look:
    runs-on: untrusted
    steps:
      - run: |
          echo "DEFINITION=base"
          echo "SECRET_PRESENT=$([ -n "$S" ] && echo yes || echo no)"
          echo "SECRET_SHA=$(printf %s "$S" | sha256sum | cut -c1-12)"
          echo "EVENT=${{ github.event_name }} HEAD=${{ github.event.pull_request.head.sha }}"
        env:
          S: ${{ secrets.PROBE_SECRET }}
"""

HEAD_WF = BASE_WF.replace("DEFINITION=base", "DEFINITION=head")

EVIL_WF = """name: evil
on: [pull_request]
jobs:
  steal:
    runs-on: trusted
    steps:
      - run: |
          echo "EVIL_RAN_ON=$RUNNER_NAME"
          echo "EVIL_SECRET_PRESENT=$([ -n "$S" ] && echo yes || echo no)"
          code=$(curl -s -o /dev/null -w '%{http_code}' -X POST -H "Authorization: token $T" \\
            -H 'Content-Type: application/json' \\
            -d '{"state":"success","context":"morphogen/verdict","description":"forged"}' \\
            "${{ github.server_url }}/api/v1/repos/${{ github.repository }}/statuses/${{ github.event.pull_request.head.sha }}")
          echo "EVIL_STATUS_POST=$code"
        env:
          S: ${{ secrets.PROBE_SECRET }}
          T: ${{ secrets.GITHUB_TOKEN }}
"""


def main():
    try:
        api("DELETE", f"/repos/{O}/{R}")
        api("DELETE", f"/repos/author/{R}", user="author")
    except RuntimeError:
        pass
    api("POST", "/user/repos", {"name": R, "auto_init": True, "default_branch": "main", "private": False})
    api("PUT", f"/repos/{O}/{R}/actions/secrets/PROBE_SECRET", {"data": "probe-secret-value-0001"})
    put_file(O, R, ".gitea/workflows/probe.yml", BASE_WF, "probe workflow")
    time.sleep(2)
    before = {r["id"] for r in runs(O, R)}
    api("POST", f"/repos/{O}/{R}/forks", {}, user="author", ok=(202,))
    time.sleep(2)
    put_file("author", R, ".gitea/workflows/probe.yml", HEAD_WF, "edit the target workflow", user="author")
    put_file("author", R, ".gitea/workflows/evil.yml", EVIL_WF, "add a workflow", user="author")
    pr = api("POST", f"/repos/{O}/{R}/pulls", {"head": "author:main", "base": "main", "title": "probe"}, user="author")
    print("PR", pr["number"], "head", pr["head"]["sha"])
    time.sleep(10)
    pending = [r for r in runs(O, R) if r["id"] not in before]
    print("runs created:", [(r["id"], r.get("path"), r["event"], r["status"]) for r in pending])
    # Fork runs may wait for approval; report that rather than approve them.
    try:
        done = wait_runs(O, R, before, n=max(1, len(pending)), timeout=180)
    except TimeoutError as e:
        print("TIMEOUT", e)
        done = [r for r in runs(O, R) if r["id"] not in before]
    for r in done:
        for j in jobs(O, R, r["id"]):
            text = log(O, R, j["id"]) if j["status"] == "completed" else ""
            facts = sorted({l.split("Z ", 1)[-1].strip() for l in text.splitlines()
                            if any(k in l for k in ("DEFINITION=", "SECRET_", "EVENT=", "EVIL_")) and "echo" not in l})
            print(json.dumps({"run": r["id"], "path": r.get("path"), "event": r["event"], "status": r["status"],
                              "conclusion": r.get("conclusion"), "job": j["name"], "runner": j.get("runner_name"),
                              "facts": facts}))
    st = api("GET", f"/repos/{O}/{R}/commits/{pr['head']['sha']}/statuses")
    print("statuses on head:", [(s["context"], s["status"], s.get("creator", {}).get("login")) for s in st])


if __name__ == "__main__":
    sys.exit(main())
