"""A build request -> a candidate provider in an experiment directory. No database.

A build request (the planner's, auto lane: it changes nothing running) names the provider to improve
(oa:hasTarget urn:kk:provider:<name>), its slot (dcterms:subject urn:kk:slot:<slot>) and what is wanted
(oa:bodyValue). The builder makes `intent/experiments/<id>/` with `experiment.yaml` and one candidate
provider directory, by one of two strategies:

  fixture   copy a prepared candidate (KK_BUILDER_FIXTURES/<slot>/<name>/): what CI uses
  harness   copy the incumbent, then run an agent harness on the copy (KK_BUILDER_COMMAND, a command
            line with {workdir} and {prompt} placeholders; e.g. `claude -p --model haiku ...`) with a
            prompt naming the request, the slot's case set and benchmark: the gate run uses this

Either way the result must be a provider of the slot (provider.yaml with that slot, a runner and a
service) with an id of its own. Whether it is any good is not the builder's call (invariant 5): the
slot's contract, the sandbox and the evaluator decide.
"""
from __future__ import annotations

import hashlib
import re
import shlex
import shutil
import subprocess
from pathlib import Path

import yaml

from morphogen.experiments import experiment_id, provider_dir

ROOT = Path(__file__).resolve().parents[4]
NAME = re.compile(r"[a-z0-9][a-z0-9-]*")


def incumbent_dir(provider: str) -> Path | None:
    """urn:kk:provider:<name> -> its directory (Morphogen's modules, then the kernel's providers)."""
    return provider_dir(provider)


def prompt(request: dict, slot: str, incumbent: Path, workdir: Path) -> str:
    cases = ROOT / "morphogen" / "contract" / "slots" / slot
    return f"""You are improving one provider of Morphogen's `{slot}` slot.

What is wanted: {request['text']}

The incumbent provider is copied into {workdir}. Change the copy so that:
- it still passes every case of the slot's contract: the case files in {cases}/cases, which
  `python3 tests/contract.py` runs (it prints "ok: <case id>" for each passing case);
- it does better on the slot's benchmark ({cases}/benchmark.yaml) than the incumbent;
- provider.yaml gets an id of its own (urn:kk:provider:<new-name>), a name, and keeps the slot, the runner
  and the service, pointing at the renamed package if you rename it.
Keep the agent and role the incumbent uses. Do not touch anything outside {workdir}.
"""


def tree_hash(d: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(x for x in d.rglob("*") if x.is_file() and "__pycache__" not in x.parts):
        h.update(str(p.relative_to(d)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def check_candidate(d: Path, slot: str, incumbent_id: str) -> dict:
    meta = yaml.safe_load((d / "provider.yaml").read_text()) if (d / "provider.yaml").exists() else None
    if not isinstance(meta, dict):
        raise ValueError("the candidate has no provider.yaml")
    if slot not in (meta.get("slots") or []):
        raise ValueError(f"the candidate does not fill {slot}")
    if not meta.get("runner") or not meta.get("service"):
        raise ValueError("the candidate needs a runner and a service")
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
            work = exp / f"{incumbent.name}-{exp_id}"
            shutil.copytree(incumbent, work, ignore=shutil.ignore_patterns("__pycache__", "_mutant"))
            (exp / "prompt.md").write_text(prompt(request, slot, incumbent, work))
            cmd = [a.replace("{workdir}", str(work)).replace("{prompt}", (exp / "prompt.md").read_text())
                   for a in shlex.split(command)]
            out = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=1800)
            (exp / "harness.log").write_text((out.stdout or "")[-20000:] + "\n--- stderr\n" + (out.stderr or "")[-5000:])
            if out.returncode:
                raise RuntimeError(f"the harness exited {out.returncode}")
        else:
            raise ValueError(f"unknown strategy {strategy!r}")
        meta = check_candidate(work, slot, yaml.safe_load((incumbent / "provider.yaml").read_text())["id"])
    except Exception:
        shutil.rmtree(exp, ignore_errors=True)
        raise
    rel = lambda p: str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)
    (exp / "experiment.yaml").write_text(yaml.safe_dump({"slot": slot, "incumbent": rel(incumbent), "candidate": work.name,
                                                         "request": request["iri"], "strategy": strategy}, sort_keys=False))
    return {"id": exp_id, "dir": exp, "candidate": work.name, "provider": meta["id"], "name": meta.get("name", meta["id"]),
            "sha256": tree_hash(work)}
