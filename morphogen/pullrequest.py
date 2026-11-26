"""A pull request, judged without a person at the keyboard: what the GitHub judge (.github/workflows/judge.yml) runs.

    morphogen pr --base BASE --head HEAD --sandbox docker [--local FILE] [--target cell:NAME | --body-env VAR]
                 [--protect GLOB ...] [--label KEY=VALUE ...] [--pull] --out verdict.json

It decides nothing itself. It works out what to hand the judge, writes it as a request (request.py) outside the
repository, and runs that request, so every rule the judge keeps holds here unchanged: the rules come from the base
commit, a candidate that changes a catalog file is refused, the held-out answers go only to the base's scorer.

- The candidate is HEAD when BASE is one of its ancestors, otherwise HEAD merged onto BASE (git merge-tree, nothing
  checked out), so the rules are always those of BASE as it is now and the diff is only the pull request's.
- A pull request that touches a `--protect` path (the caller's workflows, say) is refused before anything runs.
- One that touches no file any cell may change, and no rule file, is not judged: there is nothing to measure, and
  nothing of the judge's changes.
- Otherwise it is judged: `kind: judge` on the target the caller names (`--target`, or a line
  `morphogen-target: cell:NAME` in the pull request's description), else `kind: change` (the tests of everything the
  change touches, by default deny).
- `--local` is the operator's morphogen.local.yaml (held-out answer paths, inputs, env, services), from wherever the
  operator keeps it (a private repository); relative paths in it are read from its own directory. It may carry no
  rules: anything a request's `local` does not take is refused. `--sandbox` replaces its sandbox; `none` is refused
  unless `--unsandboxed` (tests and trials on your own machine: without a container a candidate can read the answers).

The verdict document (`pr-verdict/v1`) holds the decision, the judge's whole result and the evidence record, and is
written to `--out` whatever happens: a judge that cannot judge writes `stop`, never a pass.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

import yaml
from pydantic import ValidationError

from . import judge as judge_mod
from .documents import DocumentError
from .errors import JudgeError
from .project import FILE, LOCAL, ProjectError, _glob_re
from .request import Local, run as run_request
from .runner import RUNNERS

VERSION = "pr-verdict/v1"
TARGET_LINE = re.compile(r"^[ \t>]*morphogen-target:[ \t]*(\S+)[ \t]*$", re.MULTILINE)
SANDBOXES = ("podman", "docker", "none")


class PullRequestError(JudgeError):
    """What the caller handed over cannot be judged as it is."""


def _git(repo: Path, *args: str, env: dict | None = None, check: bool = True) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True,
                       env={**os.environ, **(env or {})})
    if check and r.returncode != 0:
        raise PullRequestError(f"git {args[0]}: {r.stderr.strip()[-300:]}")
    return r


def target_from(body: str | None) -> str | None:
    """The target a pull request's description names, on a line `morphogen-target: cell:NAME`, or None."""
    found = sorted(set(TARGET_LINE.findall(body or "")))
    if len(found) > 1:
        raise PullRequestError(f"the description names {len(found)} targets ({', '.join(found)}); name one")
    return found[0] if found else None


def candidate_of(repo: Path, base_sha: str, head_sha: str) -> tuple[str, bool]:
    """(the commit to judge, whether it is a merge made here). HEAD itself when BASE is its ancestor; otherwise HEAD
    merged onto BASE without a checkout, so the rules are the current base's and the diff is only HEAD's."""
    if _git(repo, "merge-base", "--is-ancestor", base_sha, head_sha, check=False).returncode == 0:
        return head_sha, False
    m = _git(repo, "merge-tree", "--write-tree", "--no-messages", base_sha, head_sha, check=False)
    if m.returncode != 0:
        raise PullRequestError(f"{head_sha[:12]} does not merge cleanly onto {base_sha[:12]}: update the branch")
    tree = m.stdout.split()[0]
    who = {"GIT_AUTHOR_NAME": "morphogen", "GIT_AUTHOR_EMAIL": "judge@invalid",
           "GIT_COMMITTER_NAME": "morphogen", "GIT_COMMITTER_EMAIL": "judge@invalid"}
    sha = _git(repo, "commit-tree", tree, "-p", base_sha, "-p", head_sha, "-m",
               f"morphogen: {head_sha[:12]} merged onto {base_sha[:12]}", env=who).stdout.strip()
    return sha, True


def local_from(path: Path | None, sandbox: str) -> dict:
    """The operator's local settings as a request's `local`: relative paths resolved against the file's directory,
    the sandbox replaced. Anything a request's `local` does not take (a rule, a cell's `change`) is refused."""
    data: dict = {}
    if path is not None:
        path = Path(path)
        try:
            data = yaml.safe_load(path.read_text()) or {}
        except (OSError, yaml.YAMLError) as e:
            raise DocumentError(path, [f"cannot read: {e}"]) from None
        if not isinstance(data, dict):
            raise DocumentError(path, ["the local settings are a mapping"])
        here = path.resolve().parent

        def at(p):
            return str((here / Path(p).expanduser()).resolve()) if isinstance(p, str) else p
        for cell in (data.get("cells") or {}).values():
            if isinstance(cell, dict):
                for k in ("private", "search", "inputs"):
                    if cell.get(k):
                        cell[k] = at(cell[k])
        if isinstance(data.get("env"), dict) and data["env"].get("file"):
            data["env"]["file"] = at(data["env"]["file"])
    data["sandbox"] = sandbox
    try:
        return Local.model_validate(data).model_dump(exclude_none=True)
    except ValidationError as e:
        problems = [f"{'.'.join(map(str, err['loc']))}: " + ("not a local setting (the rules come from the base "
                    "commit)" if err["type"] == "extra_forbidden" else err["msg"]) for err in e.errors()]
        raise DocumentError(path or "local", problems) from None


def _base_project(repo: Path, base_sha: str):
    """The base's catalog (read from the commit, never a working copy), or None when the base has none."""
    from .project import Project, git_reader, read_catalog
    reader = git_reader(repo, base_sha)
    try:
        reader(FILE)
    except OSError:
        return None
    try:
        cells, ifaces, origin, settings, files = read_catalog(reader, [FILE])
        return Project.from_parts(cells, ifaces, origin, settings, files, f"{base_sha[:12]}:{FILE}")
    except ProjectError as e:
        raise JudgeError(f"{FILE} on the base commit: {e}") from None


def _pull(repo: Path, base_sha: str, local: dict) -> None:
    """Fetch the sandbox image (the base's, or the operator's) before any run, so no run waits on the network."""
    from .documents import rules_config
    mode = local["sandbox"]
    if mode == "none":
        return
    settings = {k: local[k] for k in ("sandbox", "sandbox_image") if k in local}
    image = rules_config(repo, base_sha, {"local": {"cells": {}, "settings": settings}})["sandbox_image"]
    r = subprocess.run([mode, "pull", "--quiet", image], capture_output=True, text=True)
    if r.returncode != 0:
        raise JudgeError(f"{mode} pull {image}: {r.stderr.strip()[-300:]}")


def _summary(doc: dict) -> str:
    v, why = doc["verdict"], "; ".join(doc.get("reasons") or [])
    head = {"pass": "pass", "fail": "fail", "not-judged": "pass (not judged)", "stop": "stop"}[v]
    what = doc.get("target") or ("change" if doc.get("kind") == "change" else "")
    line = f"{head}{' ' + what if what else ''}{': ' + why if why else ''}"
    return line if len(line) <= 138 else line[:137] + "…"


def judge_pr(repo: Path, base: str, head: str, *, sandbox: str, local_file: Path | None = None,
             target: str | None = None, body: str | None = None, protect: list[str] = (),
             labels: dict[str, str] | None = None, unsandboxed: bool = False, pull: bool = False,
             workdir: Path | None = None) -> dict:
    """Judge HEAD against BASE as the GitHub judge does; the pr-verdict/v1 document."""
    if sandbox not in SANDBOXES:
        raise PullRequestError(f"sandbox must be one of {', '.join(SANDBOXES)}")
    if sandbox == "none" and not unsandboxed:
        raise PullRequestError("sandbox none lets a candidate read the held-out answers; the GitHub judge runs every "
                               "candidate in a container (podman or docker)")
    repo = judge_mod.repo_root(Path(repo))
    base_sha, head_sha = judge_mod.resolve(repo, base), judge_mod.resolve(repo, head)
    target = target or target_from(body)
    local = local_from(local_file, sandbox)
    cand_sha, merged = candidate_of(repo, base_sha, head_sha)
    doc = {"morphogen": VERSION, "base": base_sha, "head": head_sha, "candidate": cand_sha, "merged": merged,
           "target": target, "kind": None, "judged": False, "labels": dict(labels or {})}
    changed = judge_mod._changed(repo, base_sha, cand_sha)
    proj = _base_project(repo, base_sha)
    protected = sorted(p for p in changed if any(_glob_re(g).match(p) for g in protect))
    rules = sorted(p for p in changed if p in (FILE, LOCAL) or (proj is not None and p in proj.rule_files))
    if protected:
        from .evidence import Evidence
        rec = Evidence.for_project(repo).append({
            "claim": f"pull request {head_sha[:12]} against {base_sha[:12]} is refused: it changes protected paths",
            "kind": "verdict", "verdict": "fail", "subject": {"system": "", "path": "pull-request"},
            "method": "the caller's protected paths, from the base's workflow; refused before anything runs",
            "outcome": {"protected": protected, "changed": changed},
            "refs": {"base": base_sha, "candidate": cand_sha}, "gate": {"decision": "none"},
            "sandbox": sandbox, "runner": {"runner": sandbox, **RUNNERS[sandbox]},
            "labels": doc["labels"], "trust": "measured", "by": "judge"})
        doc.update(verdict="fail", judged=True, reasons=[f"changes protected paths: {', '.join(protected)}"],
                   gate={"decision": "none"}, evidence=rec)
        return {**doc, "summary": _summary(doc)}
    if proj is None:
        if rules:
            doc.update(verdict="fail", judged=True, gate={"decision": "none"},
                       reasons=[f"adds {FILE} to a base that has none: the first catalog reaches the base by review"])
        else:
            doc.update(verdict="not-judged", reasons=[f"no {FILE} on the base: nothing to judge by"])
        return {**doc, "summary": _summary(doc)}
    owned = [p for p in changed if any(proj.allows([c], p) for c in proj.doc.cells)]
    if not changed or not (owned or rules):
        doc.update(verdict="not-judged", reasons=["changes no file a cell may change, and no rule file"]
                   if changed else ["changes nothing"])
        return {**doc, "summary": _summary(doc)}

    kind = "judge" if target else "change"
    request = {"morphogen": "request/v1", "kind": kind, "project": str(repo), "base": base_sha,
               "candidate": cand_sha, "labels": doc["labels"], "local": local,
               **({"target": target} if target else {})}
    if pull:
        _pull(repo, base_sha, local)
    with tempfile.TemporaryDirectory(prefix="morphogen-pr-", dir=workdir) as t:
        f = Path(t) / "request.yaml"      # outside the repository: request.load refuses one inside it
        f.write_text(yaml.safe_dump(request, sort_keys=True))
        result = run_request(f)
    from .evidence import Evidence
    rec = next((r for r in reversed(Evidence.for_project(repo).dump()) if r.get("seq") == result.get("evidence_seq")),
               None)
    doc.update(verdict=result["verdict"], judged=True, kind=kind, reasons=result.get("reasons") or [],
               gate=result.get("gate"), result=result, evidence=rec)
    return {**doc, "summary": _summary(doc)}


def main(a) -> int:
    """`morphogen pr`: write the verdict document to --out whatever happens; exit 0 on a pass (judged or not),
    1 on a fail, 2 when the judge could not judge (a `stop`)."""
    out = Path(a.out)
    labels = {}
    for item in a.label or []:
        k, sep, v = item.partition("=")
        if not sep or not k:
            raise PullRequestError(f"a label is KEY=VALUE, not {item!r}")
        labels[k] = v
    try:
        doc = judge_pr(Path.cwd(), a.base, a.head, sandbox=a.sandbox, local_file=Path(a.local) if a.local else None,
                       target=a.target, body=os.environ.get(a.body_env) if a.body_env else None,
                       protect=a.protect or [], labels=labels, unsandboxed=a.unsandboxed, pull=a.pull)
        code = 0 if doc["verdict"] in ("pass", "not-judged") else 1
    except (JudgeError, DocumentError, ProjectError, KeyError, LookupError, RuntimeError) as e:
        doc = {"morphogen": VERSION, "verdict": "stop", "judged": False, "reasons": [f"the judge could not judge: {e}"]}
        doc["summary"] = _summary(doc)
        code = 2
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=2, default=str, sort_keys=True) + "\n")
    print(doc["summary"])
    return code


__all__ = ["VERSION", "PullRequestError", "judge_pr", "target_from", "candidate_of", "local_from", "main"]
