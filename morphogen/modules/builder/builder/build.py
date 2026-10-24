"""A build request -> a candidate provider in an experiment directory. No database.

A build request (the planner's, auto lane: it changes nothing running) names the provider to improve
(oa:hasTarget urn:kk:provider:<name>), its slot (dcterms:subject urn:kk:slot:<slot>) and what is wanted
(oa:bodyValue). The builder makes `intent/experiments/<id>/` with `experiment.yaml` and one candidate
provider directory, by one of two strategies:

  fixture   copy a prepared candidate (KK_BUILDER_FIXTURES/<slot>/<name>/): what CI uses
  harness   copy the incumbent into a temporary directory outside the repository and intent, then run
            an agent harness there (KK_BUILDER_COMMAND, a command line with {workdir} and {prompt}
            placeholders; e.g. `claude -p --model haiku ...`) with a prompt naming the request, the
            slot's case set and benchmark: the gate run uses this. The harness gets this process's
            environment without the record's and telemetry's credentials (DATABASE_URL, PG*, OTEL_*,
            KK_*, GIT_*); if the repository's or intent's git state changed while it ran, the build fails.
            Only the workdir is copied into the experiment. This is a check, not a sandbox: an unattended
            harness needs a container (R5-22).

Either way the result must be a provider of the slot (provider.yaml with that slot and a service) with an
id of its own, and no migration.sql but the incumbent's, unchanged (a candidate gets no grants of its own).
Whether it is any good is not the builder's call (invariant 5): the slot's own contract runner, the
sandbox and the evaluator decide.
"""
from __future__ import annotations

import re
import shlex
import shutil
import os
import subprocess
import tempfile
from pathlib import Path

import yaml

from morphogen.experiments import experiment_id, provider_dir, tree_hash

ROOT = Path(__file__).resolve().parents[4]
NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


def incumbent_dir(provider: str) -> Path | None:
    """urn:kk:provider:<name> -> its directory (Morphogen's modules, then the kernel's providers)."""
    return provider_dir(provider)


def prompt(request: dict, slot: str, incumbent: Path, workdir: Path) -> str:
    cases = ROOT / "morphogen" / "contract" / "slots" / slot
    bench = cases / "benchmark.yaml"
    benchmark = bench.read_text() if bench.exists() else "(none)"
    return f"""You are improving one provider of Morphogen's `{slot}` slot.

What is wanted: {request['text']}

The incumbent provider is copied into {workdir}. Change the copy so that:
- it still passes every case of the slot's contract: the case files in {cases}/cases. Run
  `python3 {cases}/runner.py {workdir}`: it prints "ok: <case id>" for each passing case and must exit 0;
- it does better than the incumbent on the slot's benchmark, which measures this:
{benchmark}
- provider.yaml gets an id of its own (urn:kk:provider:<new-name>, lower-case letters, digits and hyphens),
  a name, and keeps the slot, the runner and the service; if you rename the package, the service and the
  slot runner imports <package>.detect.
Keep the agent and role the incumbent uses (AGENT, KK_ROLE) and its migration.sql unchanged. Do not touch
anything outside {workdir}.
When you are done, say in one line what you changed.
"""


SECRET = ("DATABASE_URL", "PG", "OTEL_", "KK_", "GIT_")


def harness_env() -> dict:
    """This process's environment without the record's, telemetry's and git's settings."""
    return {k: v for k, v in os.environ.items() if not k.startswith(SECRET)}


def git_state(d: Path) -> str:
    """HEAD and the work tree's status of the git repository at d ("" when d is not one)."""
    run = lambda *a: subprocess.run(["git", "-C", str(d), *a], capture_output=True, text=True).stdout
    return run("rev-parse", "HEAD") + run("status", "--porcelain", "--untracked-files=all")


def check_candidate(d: Path, slot: str, incumbent_id: str, incumbent: Path | None = None) -> dict:
    meta = yaml.safe_load((d / "provider.yaml").read_text()) if (d / "provider.yaml").exists() else None
    if not isinstance(meta, dict):
        raise ValueError("the candidate has no provider.yaml")
    if slot not in (meta.get("slots") or []):
        raise ValueError(f"the candidate does not fill {slot}")
    if not meta.get("service"):
        raise ValueError("the candidate needs a service")
    if incumbent is not None:
        mine, theirs = d / "migration.sql", incumbent / "migration.sql"
        if mine.exists() and (not theirs.exists() or mine.read_bytes() != theirs.read_bytes()):
            raise ValueError("the candidate's migration.sql differs from the incumbent's")
    cid = str(meta.get("id", ""))
    if cid == incumbent_id or not cid.startswith("urn:kk:provider:") or not NAME.fullmatch(cid.removeprefix("urn:kk:provider:")):
        raise ValueError(f"the candidate needs an id of its own, not {cid!r}")
    return meta


def build(request: dict, slot: str, incumbent: Path, experiments: Path, strategy: str,
          fixtures: Path | None = None, command: str | None = None) -> dict:
    """Make the experiment directory; returns {id, dir, candidate, provider, sha256}."""
    exp_id = experiment_id(request["iri"])
    exp = experiments / exp_id
    if exp.exists():
        shutil.rmtree(exp)
    exp.mkdir(parents=True)
    try:
        if strategy == "fixture":
            src = next((p for p in sorted((fixtures / slot).iterdir()) if (p / "provider.yaml").exists()), None) if fixtures else None
            if src is None:
                raise ValueError(f"no fixture candidate for {slot}")
            work = exp / src.name
            shutil.copytree(src, work, ignore=shutil.ignore_patterns("__pycache__"))
        elif strategy == "harness":
            if not command:
                raise ValueError("the harness strategy needs KK_BUILDER_COMMAND")
            name = f"{incumbent.name}-{exp_id}"
            with tempfile.TemporaryDirectory(prefix="kk-build-") as tmp:
                scratch = Path(tmp) / name
                shutil.copytree(incumbent, scratch, ignore=shutil.ignore_patterns("__pycache__", "_mutant"))
                (exp / "prompt.md").write_text(prompt(request, slot, incumbent, scratch))
                cmd = [a.replace("{workdir}", str(scratch)).replace("{prompt}", (exp / "prompt.md").read_text())
                       for a in shlex.split(command)]
                watched = [ROOT, experiments.parent]
                before = [git_state(x) for x in watched]
                out = subprocess.run(cmd, cwd=scratch, capture_output=True, text=True, timeout=1800, env=harness_env())
                changed = [str(x) for x, b in zip(watched, before) if git_state(x) != b]
                (exp / "harness.log").write_text((out.stdout or "")[-20000:] + "\n--- stderr\n" + (out.stderr or "")[-5000:])
                if changed:
                    raise RuntimeError(f"the harness changed files outside its workdir: {changed}")
                if out.returncode:
                    raise RuntimeError(f"the harness exited {out.returncode}")
                if any(x.is_symlink() for x in scratch.rglob("*")):
                    raise ValueError("the candidate contains a symbolic link")
                work = exp / name
                shutil.copytree(scratch, work, ignore=shutil.ignore_patterns("__pycache__"))
        else:
            raise ValueError(f"unknown strategy {strategy!r}")
        meta = check_candidate(work, slot, yaml.safe_load((incumbent / "provider.yaml").read_text())["id"], incumbent)
    except Exception:
        shutil.rmtree(exp, ignore_errors=True)
        raise
    rel = lambda p: str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)
    (exp / "experiment.yaml").write_text(yaml.safe_dump({"slot": slot, "incumbent": rel(incumbent), "candidate": work.name,
                                                         "request": request["iri"], "strategy": strategy}, sort_keys=False))
    return {"id": exp_id, "dir": exp, "candidate": work.name, "provider": meta["id"], "name": meta.get("name", meta["id"]),
            "sha256": tree_hash(work)}
