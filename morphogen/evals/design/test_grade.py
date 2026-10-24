"""The design eval's grader fails what it should (a green eval counts only after it has failed with the logic
broken): the scripted interviewer passes; one that leaves out the last answer and gets an image wrong fails on the
map, the limit, the gaps and proposability; one that records nothing fails too.

  PGHOST=... PGUSER=<superuser> python3 morphogen/evals/design/test_grade.py
"""
import importlib.util
import shutil
import subprocess
import tempfile
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("design_eval", HERE / "run.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def case(db: str, script=None) -> dict:
    ev.setup(db)
    real = ev.FIX
    try:
        if script is not None:
            d = Path(tempfile.mkdtemp())
            shutil.copy(real / "notes.jsonl", d)
            (d / "notes.yaml").write_text(yaml.safe_dump(script))
            ev.FIX = d
        if script is None or script["answers"]:
            ev.reference(db)
        return ev.grade(db, db)
    finally:
        ev.FIX = real
        subprocess.run(["dropdb", "--force", db], check=True)
        subprocess.run(["dropuser", "--if-exists", ev.role(db)], check=True)


good = case("kk_design_grade_ok")
check(good["passed"], "the scripted interviewer passes")
script = yaml.safe_load((ev.FIX / "notes.yaml").read_text())
script["answers"] = script["answers"][:2]
script["answers"][1]["claims"][0][2:] = ['"ghcr.io/example/notes-web:9.9"', "The web is"]
bad = case("kk_design_grade_bad", script)
check(not bad["passed"] and not bad["map"] and not bad["limit"] and not bad["no_gaps"] and not bad["proposable"],
      "an interviewer that leaves out the last answer and gets an image wrong fails")
empty = case("kk_design_grade_empty", {"source": "notes", "system": "notes", "answers": []})
check(not empty["passed"] and not empty["no_gaps"], "an interviewer that records nothing fails (no gaps on an empty map is not a pass)")
print("design eval grader tests passed")
