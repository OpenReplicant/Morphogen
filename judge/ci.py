"""The judge's CI steps as one command line, shared by the Gitea and GitHub Actions workflows so the
two cannot drift. Standard library plus git; never imports or runs the candidate's code.

    python -m judge.ci fetch    ...   base and candidate trees as files (no hooks, no .git)
    python -m judge.ci inputs   ...   the held-out inputs for the untrusted run, never the answers
    python -m judge.ci claim    ...   claim this verdict's place in the case set's served count
    python -m judge.ci post     ...   post the verdict as the `morphogen/verdict` commit status
    python -m judge.ci summary  ...   the verdict as Markdown for the forge's checks view
"""

import argparse
import base64
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

from . import store

CONTEXT = "morphogen/verdict"


def _git(cwd, *args, auth=None, capture=True):
    cmd = ["git", "-C", str(cwd)]
    if auth:
        cmd += ["-c", f"http.extraHeader=Authorization: {auth}"]
    return subprocess.run(cmd + list(args), check=True, capture_output=capture, text=True).stdout.strip()


def _auth(token_env):
    """An HTTP Authorization header from a token in the environment (works on Gitea and GitHub)."""
    tok = os.environ.get(token_env or "", "")
    if not tok:
        return None
    return "Basic " + base64.b64encode(f"x-access-token:{tok}".encode()).decode()


def _output(name, value):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a") as f:
            f.write(f"{name}={value}\n")
    print(f"{name}={value}")


def fetch(a):
    """Fetch the base branch and the pull request's head as git objects, check the head is the one the
    event named, and write each requested tree as plain files. Nothing in the trees is executed."""
    repo = Path(a.workdir) / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    auth = _auth(a.token_env)
    url = f"{a.server}/{a.repo}.git"
    refs = [f"refs/heads/{a.base_ref}:refs/mg/base"]
    if "candidate" in a.trees or a.admit:
        refs.append(f"refs/pull/{a.pr}/head:refs/mg/head")
    _git(repo, "fetch", "-q", "--no-tags", "--force", url, *refs, auth=auth)
    base = _git(repo, "rev-parse", "refs/mg/base")
    if a.expect_base and base != a.expect_base:
        sys.exit(f"base moved: {base} != {a.expect_base}")
    if len(refs) > 1 and _git(repo, "rev-parse", "refs/mg/head") != a.head_sha:
        sys.exit("the pull request's head is not the commit this event named")
    for tree, ref in (("base", "refs/mg/base"), ("candidate", "refs/mg/head")):
        if tree in a.trees:
            out = Path(a.workdir) / tree
            out.mkdir(parents=True, exist_ok=True)
            archive = subprocess.run(["git", "-C", str(repo), "archive", ref], check=True, capture_output=True).stdout
            subprocess.run(["tar", "-x", "-C", str(out)], input=archive, check=True)
    _output("base", base)


def _card_set(admission):
    adm = json.loads(Path(admission).read_text())
    if adm.get("refused") or not adm.get("card"):
        return None
    return store.check_name(adm["card"]["cases"]["set"])  # admission already checked; belt and braces


def inputs(a):
    name = _card_set(a.admission)
    rows = store.inputs(store.DirStore(a.cases_dir), name) if name else []
    Path(a.out).write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"{len(rows)} inputs for case set {name!r}")


def claim(a):
    """Count this verdict against its case set, in the case store (a git clone at --cases-dir)."""
    name = _card_set(a.admission)
    if name is None:
        _output("served", 0)
        _output("set", "")
        return
    url = _git(a.cases_dir, "remote", "get-url", "origin")
    served = store.GitStore(url, branch=a.branch, workdir=a.cases_dir, auth=_auth(a.token_env),
                            attempts=a.attempts).claim(name)
    _output("served", served)
    _output("set", name)


def post(a):
    v = json.loads(Path(a.verdict).read_text())
    state = "success" if v["decision"] == "pass" else "failure"
    body = {"state": state, "context": CONTEXT, "description": f"{v['decision']}: {v['reason']}"[:138],
            "target_url": a.target_url}
    req = urllib.request.Request(f"{a.api}/repos/{a.repo}/statuses/{v['candidate']}", method="POST",
                                 data=json.dumps(body).encode())
    req.add_header("Authorization", f"token {os.environ[a.token_env]}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        print(f"posted {CONTEXT}={state} ({r.status})")


def _num(x):
    return "-" if x is None else f"{x:.3g}"


def plain(v):
    """The verdict in plain words, for a person who has not read the docs."""
    if v.get("judged") is False:
        if v["decision"] == "pass":
            return ["**Not judged.** The change touches nothing the judge measures, so it passes without a test."]
        return ["**Refused, for a person to decide.** " + v["reason"]]
    head = {"pass": "**Better.** The change may merge.", "refuse": "**Not shown better.** The change may not merge.",
            "stop": "**No judgment.** The judge could not judge this change; this is not the change's fault."}
    out = [head[v["decision"]], ""]
    if not v["kpis"]:
        return out + [v["reason"]]
    for k in v["kpis"]:
        p, unit = k["paired"], {"lower": "lower is better", "higher": "higher is better"}[k["direction"]]
        line = (f"- **{k['name']}** ({unit}): {_num(k['base']['mean'])} before, {_num(k['candidate']['mean'])} after. "
                f"Better on {p['better']} of {p['n']} cases, worse on {p['worse']}, the same on {p['tied']}. ")
        if k["role"] == "decide":
            pv = k["p_value"]
            if pv is not None:
                odds = "less than once in a million" if pv < 1e-6 else f"with probability {pv:.2g}"
                line += f"If the change were no better, a result this good would happen {odds} (the bar is {v['alpha']}). "
        else:
            line += f"It must not be worse by more than {k['floor']:g}. "
        line += {"pass": "Met.", "refuse": "Not met.", "stop": "Could not be measured."}[k["result"]]
        out.append(line)
    c = v["cases"]
    out += ["", f"Measured by the judge on {c['expected']} held-out cases the change never saw "
                f"(set `{c['set']}`, {c['served']} verdict{'' if c['served'] == 1 else 's'} so far{', now stale' if c['stale'] else ''})."]
    return out


def summary(a):
    v = json.loads(Path(a.verdict).read_text())
    icon = {"pass": "PASS", "refuse": "REFUSED", "stop": "STOPPED"}[v["decision"]]
    if v.get("judged") is False:
        icon += " (not judged)"
    lines = [f"## Morphogen verdict: {icon}", "", *plain(v), "", "### Details", "", v["reason"], "",
             f"Candidate `{v['candidate'][:12]}` against base `{v['base'][:12]}`; case set "
             f"`{v['cases']['set'] or '-'}` ({v['cases']['expected']} cases, served {v['cases']['served']} verdicts"
             f"{', STALE' if v['cases']['stale'] else ''}); alpha {v['alpha']}.", ""]
    if v["kpis"]:
        lines += ["| KPI | role | base | candidate | better / worse / tied | effect | p | MDE | result |",
                  "|---|---|---|---|---|---|---|---|---|"]
        f = lambda x: "-" if x is None else f"{x:.4g}"
        for k in v["kpis"]:
            p = k["paired"]
            lines.append(f"| {k['name']} ({k['source']}, {k['direction']}) | {k['role']} | {f(k['base']['mean'])} "
                         f"| {f(k['candidate']['mean'])} | {p['better']} / {p['worse']} / {p['tied']} | {f(k['effect'])} "
                         f"| {f(k['p_value'])} | {f(k['mde'])} | {k['result']} |")
    lines += ["", f"Card `{v['card_sha256'][:12]}`, policy `{v['policy_sha256'][:12]}`. "
                  "Only the judge's own measurements decide; the signed verdict is attached to the run."]
    text = "\n".join(lines) + "\n"
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a") as fh:
            fh.write(text)
    print(text)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m judge.ci")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("fetch")
    p.add_argument("--server", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--pr", required=True)
    p.add_argument("--base-ref", required=True)
    p.add_argument("--head-sha", required=True)
    p.add_argument("--expect-base")
    p.add_argument("--trees", default="base,candidate")
    p.add_argument("--admit", action="store_true", help="fetch the head's objects even if no tree is written")
    p.add_argument("--token-env")
    p.add_argument("--workdir", default=".")
    p = sub.add_parser("inputs")
    p.add_argument("--cases-dir", required=True)
    p.add_argument("--admission", required=True)
    p.add_argument("--out", required=True)
    p = sub.add_parser("claim")
    p.add_argument("--cases-dir", required=True)
    p.add_argument("--admission", required=True)
    p.add_argument("--token-env", required=True)
    p.add_argument("--branch", default="main")
    p.add_argument("--attempts", type=int, default=20)
    p = sub.add_parser("post")
    p.add_argument("--api", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--verdict", required=True)
    p.add_argument("--token-env", required=True)
    p.add_argument("--target-url", default="")
    p = sub.add_parser("summary")
    p.add_argument("--verdict", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        a.trees = [t for t in a.trees.split(",") if t]
    {"fetch": fetch, "inputs": inputs, "claim": claim, "post": post, "summary": summary}[a.cmd](a)


if __name__ == "__main__":
    main()
