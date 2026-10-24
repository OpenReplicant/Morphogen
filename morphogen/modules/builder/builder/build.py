"""A build request -> a candidate provider in an experiment directory. No database.

A build request (the planner's, auto lane: it changes nothing running) names the provider to improve
(oa:hasTarget urn:kk:provider:<name>), its slot (dcterms:subject urn:kk:slot:<slot>) and what is wanted
(oa:bodyValue). The builder makes `intent/experiments/<id>/` with `experiment.yaml` and one candidate
provider directory, by one of two strategies:

  fixture   copy a prepared candidate (KK_BUILDER_FIXTURES/<slot>/<name>/): what CI uses
  harness   copy the incumbent into a temporary directory outside the repository and intent, then run
            an agent harness there (KK_BUILDER_COMMAND, a command line with {workdir} and {prompt}
            placeholders; e.g. `claude -p --model haiku ...`) with a prompt naming the request, the
            slot's case set and benchmark: the gate run uses this. The harness runs as an OS user of its
            own (KK_RUN_AS; morphogen.confine, R5-24), in a workdir inside a home only that user may
            write, with the allow-listed environment (PATH, HOME, locale) and only the variables named in
            KK_BUILDER_ENV (its own model credentials, e.g. ANTHROPIC_API_KEY): none of the record's,
            telemetry's or git's. It does not run while the cluster lets any login in without its
            password. If the repository's or intent's git state changed while it ran, the build fails.
            Only the workdir is copied into the experiment; then every process of the run user is ended.

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
from pathlib import Path

import yaml

from morphogen import confine
from morphogen.experiments import experiment_id, provider_dir, tree_hash
from morphogen.logins import KEEP

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
  `python3 {cases}/runner.py {workdir}`: it prints "ok: <case id>" for each passing case and must exit 0.
  The sandbox also loads every case into a database and judges what one real pass of the service submits
  (its `one_pass(conn)` in the package's `__main__`), so the way the service reads the record must find
  everything the rule needs; and on the benchmark the service must submit exactly the anomalies the
  incumbent submits on the same inputs;
- it does better than the incumbent on the slot's benchmark, which measures this:
{benchmark}
- provider.yaml gets an id of its own (urn:kk:provider:<new-name>, lower-case letters, digits and hyphens),
  a name, and keeps the slot, the runner and the service; if you rename the package, the service and the
  slot runner imports <package>.detect.
Keep the agent and role the incumbent uses (AGENT, KK_ROLE) and its migration.sql unchanged. Do not touch
anything outside {workdir}.
When you are done, say in one line what you changed.
"""


def harness_env(home: Path) -> dict:
    """The allow-listed environment (no database settings), the harness's home, and the variables
    KK_BUILDER_ENV names."""
    named = {x.strip() for x in os.environ.get("KK_BUILDER_ENV", "").split(",") if x.strip()}
    if any(n == "DATABASE_URL" or n.startswith(("PG", "KK_", "OTEL_", "GIT_")) for n in named):
        raise ValueError("KK_BUILDER_ENV may not pass the record's, telemetry's or git's settings")
    return {**{k: v for k, v in os.environ.items() if (k in KEEP and not k.startswith("PG")) or k in named},
            "HOME": str(home), "TMPDIR": str(home)}


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
          fixtures: Path | None = None, command: str | None = None, roles: list[str] | None = None) -> dict:
    """Make the experiment directory; returns {id, dir, candidate, provider, sha256}. `roles`: the cluster's
    login roles, which the harness must not reach without a password (morphogen.confine.check_cluster)."""
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
            u = confine.run_user()
            with confine.home("kk-build-") as tmp:
                env = harness_env(tmp)
                if roles is not None:
                    confine.check_cluster({**env, **{k: v for k, v in os.environ.items() if k in KEEP}}, roles)
                scratch = tmp / name
                shutil.copytree(incumbent, scratch, ignore=shutil.ignore_patterns("__pycache__", "_mutant"))
                for x in [scratch, *scratch.rglob("*")]:
                    os.chown(x, u.pw_uid, u.pw_gid, follow_symlinks=False)
                (exp / "prompt.md").write_text(prompt(request, slot, incumbent, scratch))
                cmd = [a.replace("{workdir}", str(scratch)).replace("{prompt}", (exp / "prompt.md").read_text())
                       for a in shlex.split(command)]
                watched = [ROOT, experiments.parent]
                before = [git_state(x) for x in watched]
                out = confine.run(cmd, env, timeout=1800, cwd=scratch)
                confine.kill_all()
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
