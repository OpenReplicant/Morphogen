"""A request: everything a caller passes to the judge, in one document (PLAN.md, phase 7a).

The rules (cells, interfaces, tests, settings) always come from the base commit. A request names only what
is the caller's or the operator's: which repository, which commits, what to judge, labels, and the local
settings that morphogen.local.yaml holds otherwise (held-out answer paths, inputs, the sandbox, the budget, and
what runs are served: env values and services).

    morphogen: request/v1
    kind: judge                      # judge | change | probe | measure
    project: /path/to/the/repository
    base: main
    candidate: my-branch             # not for measure
    target: cell:classify            # judge, probe, measure
    labels: {optimizer: grid}        # recorded with the verdict, never decide it
    local:                           # optional; when given, it replaces morphogen.local.yaml
      sandbox: podman
      cells: {classify: {private: /outside/answers, search: /outside/search, inputs: /outside/data}}
      env: {file: /outside/run.env, pass: [DATABASE_URL]}            # serve.py
      services: {db: {image: docker.io/library/postgres:17.6, env: [POSTGRES_PASSWORD]}}

Rules the judge enforces before anything runs: the request is a file outside the repository (a candidate
commit, or the working copy, could otherwise write it); it may not carry rules (any key not above is
refused, `cells` at the top level included); and the verdict records its digest (sha256 of its canonical
JSON), so the request a verdict answered can be shown afterwards.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from .documents import DocumentError, LOCAL_SERVED, LOCAL_SETTINGS, rules_config, validate
from .evidence import canonical

VERSION = "request/v1"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CellLocal(_Strict):
    private: str | None = None
    search: str | None = None
    inputs: str | None = None


class Local(_Strict):
    sandbox: Literal["auto", "podman", "docker", "none"] | None = None
    sandbox_image: str | None = None
    budget: dict[str, int] | None = None
    cells: dict[str, CellLocal] = {}
    env: dict[str, Any] | None = None             # serve.py checks these when the judge prepares the runs
    services: dict[str, dict[str, Any]] | None = None


class Request(_Strict):
    morphogen: Literal["request/v1"]
    kind: Literal["judge", "change", "probe", "measure"]
    project: str
    base: str = "main"
    candidate: str | None = None
    target: str | None = None
    labels: dict[str, str] = {}
    local: Local | None = None


def digest(data: dict) -> str:
    return hashlib.sha256(canonical(data).encode()).hexdigest()


def _inside(path: Path, repo: Path) -> bool:
    try:
        path.resolve().relative_to(repo.resolve())
        return True
    except ValueError:
        return False


def load(path: Path) -> tuple[Request, dict, str]:
    """(the request, its data as read, its digest). Raises DocumentError naming every problem."""
    path = Path(path)
    try:
        data = yaml.safe_load(path.read_text())
    except OSError as e:
        raise DocumentError(path, [f"cannot read: {e.strerror or e}"]) from None
    except yaml.YAMLError as e:
        raise DocumentError(path, [f"not valid YAML: {e}"]) from None
    if not isinstance(data, dict):
        raise DocumentError(path, ["a request is a mapping"])
    try:
        req = Request.model_validate(data)
    except ValidationError as e:
        problems = []
        for err in e.errors():
            where = ".".join(str(p) for p in err["loc"]) or "(top)"
            if err["type"] == "extra_forbidden":
                problems.append(f"{where}: not part of a request (the rules come from the base commit)")
            else:
                problems.append(f"{where}: {err['msg']}")
        raise DocumentError(path, problems) from None
    problems = []
    if req.kind != "measure" and not req.candidate:
        problems.append(f"candidate: a {req.kind} request names the candidate commit")
    if req.kind in ("judge", "probe", "measure") and not req.target:
        problems.append(f"target: a {req.kind} request names what to judge (cell:NAME)")
    repo = Path(req.project)
    if not (repo / ".git").exists():
        problems.append(f"project: {repo} is not a git repository")
    elif _inside(path, repo):
        problems.append(f"the request is inside the repository it judges ({path}); keep it outside, where a "
                        "candidate or the working copy cannot write it")
    if problems:
        raise DocumentError(path, problems)
    return req, data, digest(data)


def config(req: Request, cfg: dict) -> dict:
    """load_config's result with the request's `local` in place of morphogen.local.yaml, when it has one."""
    if req.local is None:
        return cfg
    local = req.local.model_dump(exclude_none=True)
    out = dict(cfg)
    out["local"] = {"cells": {k: v for k, v in (local.get("cells") or {}).items()},
                    "settings": {k: local[k] for k in LOCAL_SETTINGS if k in local}, "from": "request",
                    **{k: local[k] for k in LOCAL_SERVED if local.get(k)}}
    validate("config", {k: v for k, v in out.items() if k not in ("local", "settings_from")})
    return out


def run(path: Path) -> dict:
    """Do what the request asks; the result is what the judge returns, with the request's digest."""
    from . import judge as judge_mod
    from .documents import load_config
    from .evidence import Evidence
    req, _, dig = load(path)
    repo = judge_mod.repo_root(Path(req.project))
    cfg = config(req, load_config(repo))
    ev = Evidence.for_project(repo)
    meta = {"digest": dig, "version": VERSION, "kind": req.kind}
    if req.kind == "judge":
        out = judge_mod.judge(repo, cfg, req.target, req.base, req.candidate, ev, req.labels, request=meta)
    elif req.kind == "change":
        out = judge_mod.judge_change(repo, cfg, req.base, req.candidate, ev, request=meta)
    elif req.kind == "probe":
        out = judge_mod.probe(repo, cfg, req.target, req.candidate, ev, base=req.base, request=meta)
    else:
        out = judge_mod.measure(repo, cfg, req.target, req.base, ev, request=meta)
    return {**out, "request": meta}


__all__ = ["Request", "VERSION", "load", "config", "run", "digest", "rules_config"]
