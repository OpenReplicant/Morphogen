"""A fresh start: `status` from an empty directory to a judged first cell, one next step at a time."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from morphogen import judge as judge_mod
from morphogen.documents import load_config
from morphogen.evidence import Evidence
from morphogen.status import status
from tests.fixture import SANDBOX, git

WORK = "import time\n\nDELAY = 0.4\n\n\ndef main():\n    time.sleep(DELAY)\n    print('done')\n\n\nif __name__ == '__main__':\n    main()\n"
TEST = "import unittest\n\nimport work\n\n\nclass T(unittest.TestCase):\n    def test_runs(self):\n        self.assertGreaterEqual(work.DELAY, 0)\n"
CELL = {"change": "work.py#DELAY in 0..1", "run": "python work.py", "better": "wall_seconds lower",
        "tests": "python -m unittest -q test_work", "rounds": {"warmup": 0, "repeats": 4, "max_repeats": 8}}


class FreshStart(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = self.tmp / "proj"
        self.repo.mkdir()

    def now(self):
        cfg = load_config(self.repo) if (self.repo / ".git").exists() else None
        ev = Evidence.for_project(self.repo) if (self.repo / ".git").exists() else None
        return status(self.repo, cfg, ev)

    def write(self, rel, text):
        (self.repo / rel).write_text(text)

    def doc(self, cells, **extra):
        self.write("morphogen.yaml", yaml.safe_dump({"sandbox": SANDBOX, **extra, "cells": cells}, sort_keys=False))

    def commit(self, msg="c"):
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", msg)

    def test_from_nothing_to_a_verdict(self):
        s = self.now()
        self.assertIn("not a git repository", s["next"])

        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "test")
        s = self.now()
        self.assertIsNone(s["base"])
        self.assertIn("no commit on `main`", s["next"])

        self.write("work.py", WORK)
        self.write("test_work.py", TEST)
        self.commit("the system")
        s = self.now()
        self.assertFalse(s["sources"]["morphogen.yaml"])
        self.assertIn("no map yet", s["next"])

        # the map skill's first draft, not yet on main
        self.doc({"work": CELL})
        s = self.now()
        self.assertIn("drafted but not on `main`", s["next"])
        self.assertEqual(s["cells"], [])

        self.commit("map: one cell")   # the operator merges it
        s = self.now()
        [c] = s["cells"]
        self.assertTrue(c["ready"], c)
        self.assertEqual(c["change"], ["work.py#DELAY in 0..1"])
        self.assertIn("measure cell:work", s["next"])

        cfg, ev = load_config(self.repo), Evidence.for_project(self.repo)
        judge_mod.measure(self.repo, cfg, "cell:work", "main", ev)
        s = self.now()
        self.assertEqual(s["cells"][0]["measurements"], 1)
        self.assertIn("improve cell:work", s["next"])

        git(self.repo, "checkout", "-q", "-b", "faster")
        self.write("work.py", WORK.replace("DELAY = 0.4", "DELAY = 0.05"))
        self.commit("faster")
        git(self.repo, "checkout", "-q", "main")
        r = judge_mod.judge(self.repo, cfg, "cell:work", "main", "faster", ev)
        self.assertEqual(r["verdict"], "pass", r)
        s = self.now()
        self.assertEqual((s["cells"][0]["verdicts"], s["cells"][0]["passes"]), (1, 1))
        self.assertEqual(s["cells"][0]["last_verdict"]["verdict"], "pass")
        self.assertEqual(s["cells"][0]["last_verdict"]["gate"], "review")
        self.assertLess(s["cells"][0]["evidence_age_days"], 1)
        self.assertIn("every cell on the trunk has a verdict", s["next"])

    def test_problems_and_sources(self):
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "test")
        self.write("work.py", WORK)
        self.write("catalog-info.yaml", yaml.safe_dump({
            "apiVersion": "backstage.io/v1alpha1", "kind": "Component",
            "metadata": {"name": "work"}, "spec": {"type": "service", "lifecycle": "experimental", "owner": "me"}}))
        self.commit()
        s = self.now()
        self.assertEqual(s["sources"]["backstage"]["found"], ["catalog-info.yaml"])
        self.assertIn("backstage: [catalog-info.yaml]", s["next"])

        # a cell with a run but nothing it may change; a committed local file
        self.doc({"work": {"run": "python work.py"}}, backstage="catalog-info.yaml")
        self.write("morphogen.local.yaml", "sandbox: none\n")
        self.commit()
        s = self.now()
        names = {c["cell"]: c for c in s["cells"]}
        self.assertIn("component:default/work", names)
        self.assertFalse(names["work"]["ready"])
        self.assertIn("no `change`", names["work"]["problems"][0])
        self.assertIn("no `better`", " ".join(names["work"]["notes"]))
        self.assertTrue(any("morphogen.local.yaml is committed" in m for m in s["missing"]))
        self.assertIn("not ready to judge", s["next"])

    def test_structure_errors_on_the_trunk(self):
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "test")
        self.doc({"a": {"in": "nowhere"}})
        self.commit()
        s = self.now()
        self.assertTrue(s["errors"])
        self.assertIn("fix the structure", s["next"])

    def test_command_line(self):
        out = subprocess.run(["uv", "run", "--quiet", "morphogen", "status"], cwd=self.repo,
                             capture_output=True, text=True, check=False)
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertIn("not a git repository", out.stdout)


if __name__ == "__main__":
    unittest.main()
