"""Intent actuator (the Execute step of MAPE-K, R5-07): carries out approved plan steps by committing the
change to the provider's intent file. It never writes claims and never touches running services: each
step it carries out (or refuses) is a run of this module with `plan_step` the step and `used` its claims,
finished succeeded with the commit, or failed with the reason. A reconciler (morphogen/deploy) makes the
running system match intent; the observer records the effect.

  python -m intent_actuator [--once]

Commit messages start with `change-set:<id>` (the change sets that recorded the step) and name the plan
step, so the intent history links to the evidence. Steps it has run before (its runs with that
plan_step) are never run again.
Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_intent_actuator),
KK_INTENT_DIR (an intent directory inside a git work tree; default morphogen/intent), KK_INTENT_ENV
(default sandbox), KK_SWEEP_SECONDS.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from kk.lib import connect, follow, run
from morphogen.policy import actions

from .actuate import PPLAN_STEP_OF, intent_file, refusal, set_env, steps

MODULE = "urn:kk:module:intent-actuator"
AGENT = "urn:kk:agent:intent-actuator"
COMMITTER = {"GIT_AUTHOR_NAME": "Morphogen intent actuator", "GIT_AUTHOR_EMAIL": "intent-actuator@morphogen.invalid",
             "GIT_COMMITTER_NAME": "Morphogen intent actuator", "GIT_COMMITTER_EMAIL": "intent-actuator@morphogen.invalid"}


def git(intent: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(intent), *args], capture_output=True, text=True,
                         env={**os.environ, **COMMITTER})
    if out.returncode:
        raise RuntimeError(f"git {args[0]}: {(out.stderr or out.stdout).strip()[-300:]}")
    return out.stdout.strip()


def commit(intent: Path, f: Path, s: dict, label: str) -> str:
    rel = str(f.relative_to(intent))
    git(intent, "add", "--", rel)
    msg = f"change-set:{','.join(s['change_sets'])} plan-step:{s['step']}\n\n{label}\n\nPlan: {s['plan']}\n"
    git(intent, "commit", "-q", "-m", msg, "--", rel)
    return git(intent, "rev-parse", "HEAD")


def one_pass(conn, intent: Path, env: str) -> dict:
    acts = actions(intent)
    with conn.cursor() as cur:
        cur.execute("""select id, subject, predicate, object_entity, object_value, change_set from api.claims
                       where status <> 'deprecated' and subject in
                         (select subject from api.claims where predicate = %s and status <> 'deprecated')""",
                    (PPLAN_STEP_OF,))
        cols = [d.name for d in cur.description]
        claims = [dict(zip(cols, r)) for r in cur.fetchall()]
        cur.execute("""select id::text, 'review', decided_by, submitted_by, 'applied' from api.review_decisions
                       where id = any(%s::uuid[])""", (sorted({str(c["change_set"]) for c in claims}),))
        sets = {r[0]: dict(zip(("lane", "decided_by", "submitted_by", "status"), r[1:])) for r in cur.fetchall()}
        cur.execute("select distinct plan_step from kernel.run where agent = %s and plan_step is not null", (AGENT,))
        done = {r[0] for r in cur.fetchall()}
        cur.execute("""select subject, object_value->>'@value' from api.claims where predicate = %s
                       and subject = any(%s) and status <> 'deprecated'""",
                    ("http://www.w3.org/2000/01/rdf-schema#label", sorted({c["object_entity"] for c in claims if c["predicate"] == PPLAN_STEP_OF})))
        labels = dict(cur.fetchall())
        report = {}
        for s in steps(claims, sets):
            if s["step"] in done or not s["approved"]:
                continue                                # unapproved steps wait; they are not refused yet
            why = refusal(s, acts, intent, env)
            try:
                with run(cur, MODULE, {"action": s["action"], "target": s["target"], "value": s["value"], "plan": s["plan"]},
                         plan_step=s["step"], used=s["claims"]) as (_, outputs):
                    if why:
                        outputs.update(refused=why)
                        raise PermissionError(why)
                    f = intent_file(intent, env, s["target"])
                    setting = acts[s["action"]]["setting"]
                    before, after = set_env(f, setting, s["value"])
                    try:
                        sha = commit(intent, f, s, labels.get(s["plan"], s["plan"]))
                    except Exception:
                        git(intent, "checkout", "--", str(f.relative_to(intent)))   # leave intent as it was
                        raise
                    outputs.update(file=str(f.relative_to(intent)), setting=setting, before=before, after=after, commit=sha)
                report[s["step"]] = {"status": "succeeded", **outputs}
            except Exception as e:                      # recorded as a failed run; go on with the next step
                report[s["step"]] = {"status": "failed", "error": str(e)[:300]}
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Carry out approved plan steps as commits to intent.")
    ap.add_argument("--once", action="store_true", help="one pass, print the result and exit")
    a = ap.parse_args(argv)
    intent = Path(os.environ.get("KK_INTENT_DIR", "morphogen/intent")).resolve()
    env = os.environ.get("KK_INTENT_ENV", "sandbox")
    conn = connect(os.environ.get("KK_ROLE", "kkm_intent_actuator"))
    step = lambda c: print(json.dumps(one_pass(c, intent, env)), flush=True)
    if a.once:
        step(conn)
        return 0
    follow(conn, step)                  # an approval applies a change set: any feed entry may be one
    return 0


if __name__ == "__main__":
    sys.exit(main())
