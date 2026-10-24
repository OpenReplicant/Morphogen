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
from intent_actuator.actuate import CHECKSUM, SUBSTITUTED_BY, intent_file, replace  # noqa: E402
from morphogen.experiments import tree_hash  # noqa: E402
exp = intent / "experiments" / "x0123456789ab"
shutil.copytree(ROOT / "morphogen" / "tests" / "fixtures" / "analyser" / "anomaly-recent", exp / "anomaly-recent",
                ignore=shutil.ignore_patterns("__pycache__"))
af = intent / "environments" / "sandbox" / "anomaly.yaml"
af.write_text("provider: anomaly\nservice: python3 -m anomaly\ncwd: morphogen/modules/anomaly\nenv:\n  KK_SWEEP_SECONDS: \"2\"\n")
rs = [c("1", RDF_TYPE, SOSA + "Actuation"), c("2", PPLAN_STEP_OF, PLAN), c("3", DCT_TYPE, "urn:kk:action:replace-provider"),
      c("4", SOSA + "hasFeatureOfInterest", "urn:kk:provider:anomaly"),
      {**c("5", SUBSTITUTED_BY, "urn:kk:provider:anomaly-recent"), "qualifiers": {CHECKSUM: tree_hash(exp / "anomaly-recent")}}]
r = steps(rs, person)[0]
check(r["candidate"] == "urn:kk:provider:anomaly-recent" and refusal(r, ACTS, intent, "sandbox") is None,
      "a replacement by an experiment's candidate, approved: carried out")
check("no content hash" in refusal({**r, "sha256": None}, ACTS, intent, "sandbox"), "a replacement naming no content hash is refused")
(exp / "anomaly-recent" / "anomaly_recent" / "extra.py").write_text("x = 1\n")
check("not the code that was measured" in refusal(r, ACTS, intent, "sandbox"),
      "a candidate changed after it was measured is refused")
(exp / "anomaly-recent" / "anomaly_recent" / "extra.py").unlink()
check("not one experiment" in refusal({**r, "candidate": "urn:kk:provider:elsewhere"}, ACTS, intent, "sandbox"),
      "a candidate that is not in an experiment is refused")
change = replace(intent, af, "urn:kk:provider:anomaly-recent")
text = af.read_text()
check(change["after"] == {"provider": "anomaly-recent", "service": "python3 -m anomaly_recent",
                          "cwd": "experiments/x0123456789ab/anomaly-recent"} and 'KK_SWEEP_SECONDS: "2"' in text
      and change["before"]["cwd"] == "morphogen/modules/anomaly", "the intent file now runs the candidate; its settings stay")
check(intent_file(intent, "sandbox", "urn:kk:provider:anomaly-recent") == af and intent_file(intent, "sandbox", "urn:kk:provider:anomaly") is None,
      "the file is found by the provider it now names, not the one it was written for")

# A service of a managed system (G3, R5-25): the step changes a setting its compose file already has.
from intent_actuator.actuate import target_file  # noqa: E402
from morphogen import systems  # noqa: E402
BACK = "urn:kk:node:podinfo:backend"
ns = {**s, "action": "urn:kk:action:set-random-delay-max", "target": BACK, "value": 145}
check(refusal(ns, ACTS, intent, "sandbox") is None, "an approved step on a managed system's service: carried out")
check("not a service" in refusal({**ns, "target": "urn:kk:node:podinfo:nothing"}, ACTS, intent, "sandbox")
      and "not a service" in refusal({**ns, "target": "urn:kk:node:../etc:x"}, ACTS, intent, "sandbox")
      and "not a service" in refusal({**ns, "target": TARGET}, ACTS, intent, "sandbox"),
      "a node action on anything but a managed system's service is refused")
check("no setting" in refusal({**ns, "target": "urn:kk:node:podinfo:redis"}, ACTS, intent, "sandbox"),
      "a service whose compose file does not set it is refused (the actuator never adds settings)")
check("intent file" in refusal({**s, "target": BACK}, ACTS, intent, "sandbox"), "a provider action on a node is refused")
check("from 0 to 5000" in refusal({**ns, "value": 9000}, ACTS, intent, "sandbox"), "out of the action's bounds: refused")
check("whole number" in refusal({**ns, "value": 12.5}, ACTS, intent, "sandbox"), "a fraction for a whole-number setting: refused")
cf = target_file(intent, "sandbox", BACK, ACTS["urn:kk:action:set-random-delay-max"])
old_text = cf.read_text()
check(systems.set_setting(intent, BACK, "PODINFO_RANDOM_DELAY_MAX", 145) == ("600", "145")
      and cf.read_text() == old_text.replace('PODINFO_RANDOM_DELAY_MAX: "600"', 'PODINFO_RANDOM_DELAY_MAX: "145"'),
      "the compose file changes in that one value; every other byte stays")
from intent_actuator.__main__ import uncommitted  # noqa: E402
check(uncommitted(intent, cf), "an edit not yet committed is seen (the actuator refuses the step rather than commit it)")
subprocess.run(["git", "-C", str(intent), "checkout", "--", str(cf.relative_to(intent))], check=True)
check(not uncommitted(intent, cf), "as committed: nothing uncommitted")
link_intent = tmp / "linked"
(link_intent / "systems").mkdir(parents=True)
(link_intent / "systems" / "podinfo").symlink_to(intent / "systems" / "podinfo")
check(systems.compose_file(link_intent, BACK) is None, "a system directory that is a link is not a managed system")
try:
    systems.set_setting(intent, "urn:kk:node:podinfo:frontend", "PODINFO_RANDOM_DELAY_MAX", 1)
    check(False, "a setting the service does not have is not added")
except ValueError:
    check(True, "a setting the service does not have is not added")

# A create step (R5-29): a new system's compose file, named by the sha256 the design agent rendered.
CREATE, H = "urn:kk:action:create-system", "a" * 64
cs = lambda target, value: steps([c("1", RDF_TYPE, SOSA + "Actuation"), c("2", PPLAN_STEP_OF, PLAN), c("3", DCT_TYPE, CREATE),
                                  c("4", SOSA + "hasFeatureOfInterest", target), c("5", SOSA + "hasSimpleResult", v={"@value": value})],
                                 person)[0]
check(refusal(cs("urn:kk:system:notes", H), ACTS, intent, "sandbox") is None, "a create step for a new system, naming a sha256: carried out")
check("exists already" in refusal(cs("urn:kk:system:podinfo", H), ACTS, intent, "sandbox"),
      "a create step for a system whose compose file exists is refused (create never overwrites)")
check("exists already" in refusal(cs("urn:kk:system:../etc", H), ACTS, intent, "sandbox")
      and "exists already" in refusal(cs("urn:kk:node:notes:web", H), ACTS, intent, "sandbox"),
      "a create step must name a system by a plain name")
check("sha256" in refusal(cs("urn:kk:system:notes", 0.5), ACTS, intent, "sandbox"), "a create step must name the file's sha256")
(link_intent / "systems" / "notes").symlink_to(tmp)
check(refusal(cs("urn:kk:system:notes", H), ACTS, link_intent, "sandbox") is not None, "a system directory that is a link is refused")
shutil.rmtree(tmp)
