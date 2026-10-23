"""Intent actuator unit checks: only a step a person approved, from the fixed list, within bounds, on a
provider with an intent file, is carried out, and carrying it out is one commit naming the change set.
No database.

  python3 tests/test_actuate.py   (needs git)
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "morphogen" / "src"), str(ROOT / "kernel" / "src")]
from morphogen.policy import actions  # noqa: E402

from intent_actuator.__main__ import commit  # noqa: E402
from intent_actuator.actuate import DCT_TYPE, PPLAN_STEP_OF, RDF_TYPE, SOSA, refusal, set_env, steps  # noqa: E402


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


tmp = Path(tempfile.mkdtemp())
intent = tmp / "intent"
shutil.copytree(ROOT / "morphogen" / "intent", intent)
subprocess.run(["git", "init", "-q", str(intent)], check=True)
subprocess.run(["git", "-C", str(intent), "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A"], check=True)
subprocess.run(["git", "-C", str(intent), "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "intent"], check=True)
ACTS = actions(intent)
STEP, PLAN, TARGET = "urn:kk:plan:p1:step:1", "urn:kk:plan:p1", "urn:kk:provider:belief-corroboration"
c = lambda i, p, o=None, v=None: {"id": i, "subject": STEP, "predicate": p, "object_entity": o,
                                  "object_value": v, "change_set": "cs1"}
claims = [c("1", RDF_TYPE, SOSA + "Actuation"), c("2", PPLAN_STEP_OF, PLAN), c("3", DCT_TYPE, "urn:kk:action:set-poll-seconds"),
          c("4", SOSA + "hasFeatureOfInterest", TARGET), c("5", SOSA + "hasSimpleResult", v={"@value": 0.5})]
person = {"cs1": {"lane": "review", "decided_by": "alice", "submitted_by": "kkm_planner", "status": "applied"}}
s = steps(claims, person)[0]
check(s["approved"] and s["action"] == "urn:kk:action:set-poll-seconds" and s["value"] == 0.5 and s["target"] == TARGET,
      "an approved step: action, target and value")
check(refusal(s, ACTS, intent, "sandbox") is None, "approved, on the list, in bounds, with an intent file: carried out")
check(not steps(claims, {"cs1": {**person["cs1"], "decided_by": "kkm_planner"}})[0]["approved"], "approved by its own submitter: not approved")
check(not steps(claims, {})[0]["approved"], "no review decision: not approved")
check("fixed list" in refusal({**s, "action": "urn:kk:action:drop-database"}, ACTS, intent, "sandbox"), "an action off the list is refused")
check("intent file" in refusal({**s, "target": "urn:kk:provider:../../etc"}, ACTS, intent, "sandbox")
      and "intent file" in refusal({**s, "target": "urn:kk:provider:nothing-here"}, ACTS, intent, "sandbox"),
      "a target without an intent file (or a path in disguise) is refused")
twice = steps(claims + [c("6", SOSA + "hasSimpleResult", v={"@value": 9.0})], person)[0]
check("more than one" in refusal(twice, ACTS, intent, "sandbox"), "a step naming two values is refused")
two_sets = steps(claims + [{**c("7", SOSA + "hasSimpleResult", v={"@value": 9.0}), "change_set": "cs2"}],
                 {**person, "cs2": person["cs1"]})[0]
check("more than one" in refusal(two_sets, ACTS, intent, "sandbox"), "a step recorded by two change sets is refused")
check("from 0.1 to 30" in refusal({**s, "value": 0.0}, ACTS, intent, "sandbox")
      and "from 0.1 to 30" in refusal({**s, "value": True}, ACTS, intent, "sandbox"), "a value out of bounds is refused")

f = intent / "environments" / "sandbox" / "belief-corroboration.yaml"
before_text = f.read_text()
check(set_env(f, "KK_POLL_SECONDS", 0.5) == ("1", "0.5") and 'KK_POLL_SECONDS: "0.5"' in f.read_text()
      and f.read_text().count("\n") == before_text.count("\n") and "# Desired state" in f.read_text(),
      "the setting changes in place; comments and the rest stay")
sha = commit(intent, f, {**s, "change_sets": ["cs1"]}, "Set belief-corroboration KK_POLL_SECONDS from 1 to 0.5")
msg = subprocess.run(["git", "-C", str(intent), "log", "-1", "--format=%B%n%an"], capture_output=True, text=True).stdout
check(len(sha) == 40 and msg.startswith(f"change-set:cs1 plan-step:{STEP}") and "Morphogen intent actuator" in msg,
      "one commit, its message naming the change set and the plan step")
check(subprocess.run(["git", "-C", str(intent), "status", "--porcelain"], capture_output=True, text=True).stdout == "",
      "nothing else is changed")
from intent_actuator.__main__ import restore  # noqa: E402
set_env(f, "KK_POLL_SECONDS", 7.0)
subprocess.run(["git", "-C", str(intent), "add", "--", str(f.relative_to(intent))], check=True)
restore(intent, f)                                # as after a commit that failed once the file was staged
check(subprocess.run(["git", "-C", str(intent), "status", "--porcelain"], capture_output=True, text=True).stdout == ""
      and 'KK_POLL_SECONDS: "0.5"' in f.read_text(), "a failed commit leaves the file as committed, index and work tree")
# Replacing a provider with a measured candidate (G2).
from intent_actuator.actuate import SUBSTITUTED_BY, intent_file, replace  # noqa: E402
exp = intent / "experiments" / "x0123456789ab"
shutil.copytree(ROOT / "morphogen" / "tests" / "fixtures" / "analyser" / "anomaly-recent", exp / "anomaly-recent",
                ignore=shutil.ignore_patterns("__pycache__"))
af = intent / "environments" / "sandbox" / "anomaly.yaml"
af.write_text("provider: anomaly\nservice: python3 -m anomaly\ncwd: morphogen/modules/anomaly\nenv:\n  KK_SWEEP_SECONDS: \"2\"\n")
rs = [c("1", RDF_TYPE, SOSA + "Actuation"), c("2", PPLAN_STEP_OF, PLAN), c("3", DCT_TYPE, "urn:kk:action:replace-provider"),
      c("4", SOSA + "hasFeatureOfInterest", "urn:kk:provider:anomaly"), c("5", SUBSTITUTED_BY, "urn:kk:provider:anomaly-recent")]
r = steps(rs, person)[0]
check(r["candidate"] == "urn:kk:provider:anomaly-recent" and refusal(r, ACTS, intent, "sandbox") is None,
      "a replacement by an experiment's candidate, approved: carried out")
check("not one experiment" in refusal({**r, "candidate": "urn:kk:provider:elsewhere"}, ACTS, intent, "sandbox"),
      "a candidate that is not in an experiment is refused")
change = replace(intent, af, "urn:kk:provider:anomaly-recent")
text = af.read_text()
check(change["after"] == {"provider": "anomaly-recent", "service": "python3 -m anomaly_recent",
                          "cwd": "experiments/x0123456789ab/anomaly-recent"} and 'KK_SWEEP_SECONDS: "2"' in text
      and change["before"]["cwd"] == "morphogen/modules/anomaly", "the intent file now runs the candidate; its settings stay")
check(intent_file(intent, "sandbox", "urn:kk:provider:anomaly-recent") == af and intent_file(intent, "sandbox", "urn:kk:provider:anomaly") is None,
      "the file is found by the provider it now names, not the one it was written for")
shutil.rmtree(tmp)
