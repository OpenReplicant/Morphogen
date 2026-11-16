"""The intake: a judge held by another user (or another machine), and the one door into it.

On one machine an agent that writes candidates runs as the person it works for, so it can read whatever
that person can: the held-out answers, the request, the evidence log. A container does not change that,
because the same user starts the container. So the judge's side is another Unix user, whose home the
author's side cannot read or write:

    HOME/requests/NAME.yaml     a request (request.py) with no candidate: which project, which base, what to
                                judge, and where the held-out answers are
    HOME/projects/...           the judge's own clone of each project; verdicts go into its evidence log

The author's side may run exactly one thing as that user (a sudoers rule naming it, no password):

    git bundle create - CANDIDATE ^main | sudo -u JUDGE morphogen intake judge NAME

It hands over a name and a bundle and gets the verdict back. It never names a path, a base or a rule. The
base branch in the judge's clone moves only through `intake advance`, which is not in that rule: it is the
owner's, with their password. Otherwise an author commits weaker rules, calls that commit the base and is
judged by them.
"""

from __future__ import annotations

import os
import re
import secrets
import subprocess
import tempfile
from pathlib import Path
from typing import BinaryIO

import yaml

from .errors import JudgeError

NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,62}\Z")
LIMIT = 512 * 1024 * 1024          # the largest bundle taken, in bytes
SHA = re.compile(r"[0-9a-f]{40}([0-9a-f]{24})?\Z")


class IntakeError(JudgeError):
    """The intake refused what it was handed, or the judge's side is not set up for it."""


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    # nothing of the caller's reaches git: no config from the environment, no prompts, no hooks run by fetch
    env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": os.environ.get("HOME", "/nonexistent"),
           "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1", "LC_ALL": "C"}
    r = subprocess.run(["git", "-c", "fetch.fsckObjects=true", *args],
                       cwd=repo, env=env, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise IntakeError(f"git {args[0]} failed: {r.stderr.strip()[-300:]}")
    return r


def _request(home: Path, name: str) -> tuple[dict, Path]:
    """The request the judge's side keeps under `name`, and the judge's clone it names."""
    if not isinstance(name, str) or not NAME.match(name):
        raise IntakeError("a request is named by lower-case letters, digits and dashes: the judge's side keeps it, "
                          "and a path is never taken")
    home = Path(home).resolve()
    f = home / "requests" / f"{name}.yaml"
    if f.is_symlink() or not f.is_file():
        raise IntakeError(f"no request named {name!r} on the judge's side")
    try:
        data = yaml.safe_load(f.read_text())
    except yaml.YAMLError as e:
        raise IntakeError(f"the request {name!r} is not valid YAML: {e}") from None
    if not isinstance(data, dict) or not data.get("project"):
        raise IntakeError(f"the request {name!r} names no project")
    if data.get("candidate"):
        raise IntakeError(f"the request {name!r} already names a candidate: the candidate is what is handed over")
    repo = Path(str(data["project"])).resolve()
    if not repo.is_relative_to(home) or repo == home:
        raise IntakeError(f"the request {name!r} names a project outside the judge's home: the clone judged in "
                          "must be the judge's own")
    if not (repo / ".git").is_dir():
        raise IntakeError(f"the judge's clone for {name!r} is missing")
    return data, repo


def _take(repo: Path, bundle: BinaryIO, limit: int, tmp: Path) -> tuple[str, str]:
    """Read one bundle carrying one ref into refs/intake/ID/ of the judge's clone: (the commit, the ref prefix).
    Nothing is written under refs/heads, whatever the bundle calls its ref."""
    f = tmp / "candidate.bundle"
    size = 0
    with f.open("wb") as w:
        while chunk := bundle.read(1024 * 1024):
            size += len(chunk)
            if size > limit:
                raise IntakeError(f"the bundle is larger than the judge takes ({limit} bytes)")
            w.write(chunk)
    if size == 0:
        raise IntakeError("nothing was handed over: a git bundle is read from standard input")
    heads = _git(repo, "bundle", "list-heads", str(f), check=False)
    if heads.returncode != 0:
        raise IntakeError("what was handed over is not a git bundle")
    listed = [line.split(None, 1) for line in heads.stdout.splitlines() if line.strip()]
    listed = [x for x in listed if len(x) == 2 and x[1] != "HEAD"]
    if len(listed) != 1 or not SHA.match(listed[0][0]):
        raise IntakeError(f"a bundle carries one commit, the candidate; this one carries {len(listed)} refs")
    sha, ref = listed[0]
    if _git(repo, "bundle", "verify", str(f), check=False).returncode != 0:
        raise IntakeError("the bundle builds on commits the judge's clone does not have: the judge's base is "
                          "behind (the owner runs `intake advance`), or send the candidate's whole history")
    prefix = f"refs/intake/{secrets.token_hex(8)}"
    _git(repo, "fetch", "--quiet", "--no-tags", "--no-write-fetch-head", str(f), f"{ref}:{prefix}/candidate")
    return sha, prefix


def _drop(repo: Path, prefix: str) -> None:
    for line in _git(repo, "for-each-ref", "--format=%(refname)", prefix, check=False).stdout.splitlines():
        _git(repo, "update-ref", "-d", line.strip(), check=False)


def judge(home: Path, name: str, bundle: BinaryIO, limit: int = LIMIT) -> dict:
    """Judge the bundled candidate by the request `name`; the verdict, as request.run gives it."""
    from . import request as request_mod
    data, repo = _request(home, name)
    with tempfile.TemporaryDirectory(prefix="morphogen-intake-") as t:
        tmp = Path(t)
        sha, prefix = _take(repo, bundle, limit, tmp)
        try:
            f = tmp / "request.yaml"
            f.write_text(yaml.safe_dump({**data, "candidate": sha, "project": str(repo)}))
            return request_mod.run(f)
        finally:
            _drop(repo, prefix)


def advance(home: Path, name: str, bundle: BinaryIO, limit: int = LIMIT) -> dict:
    """Move the base branch of the judge's clone forward to the bundled commit. The owner's, never the author's:
    the base is where the rules come from."""
    data, repo = _request(home, name)
    base = str(data.get("base") or "main")
    if not NAME.match(base.lower().replace("/", "-").replace(".", "-").replace("_", "-")):
        raise IntakeError(f"the request's base {base!r} is not a branch name")
    if _git(repo, "symbolic-ref", "--short", "HEAD").stdout.strip() != base:
        raise IntakeError(f"the judge's clone is not on its base branch {base!r}")
    if _git(repo, "status", "--porcelain").stdout.strip():
        raise IntakeError("the judge's clone has changes of its own; it should hold commits only")
    with tempfile.TemporaryDirectory(prefix="morphogen-intake-") as t:
        sha, prefix = _take(repo, bundle, limit, Path(t))
        try:
            old = _git(repo, "rev-parse", "--verify", f"refs/heads/{base}").stdout.strip()
            ahead = _git(repo, "merge-base", "--is-ancestor", old, sha, check=False).returncode == 0
            if not ahead or old == sha:
                raise IntakeError(f"the base only moves forward: {sha[:12]} is not ahead of {old[:12]}")
            _git(repo, "merge", "--quiet", "--ff-only", sha)
            return {"base": sha, "was": old, "branch": base, "project": str(repo)}
        finally:
            _drop(repo, prefix)


__all__ = ["IntakeError", "judge", "advance", "NAME", "LIMIT"]
