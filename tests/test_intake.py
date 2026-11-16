"""The intake (morphogen/intake.py): the judge held by another user. The author's side hands over a candidate
as a git bundle and the name of a request the judge's side keeps; it reads and writes nothing else there.
The cheats an author could try through that one door are in IntakeCheats; each must be refused."""

import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from morphogen import intake
from morphogen.evidence import Evidence
from tests.fixture import CLASSIFY, SANDBOX, ScoredProject, git

BETTER = CLASSIFY.replace("= 10", "= 50")
PERFECT_SCORER = 'import json, sys\nsys.stdin.read()\nprint(json.dumps({"accuracy": 1.0}))\n'


def out(cwd, *args) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


class Intake(unittest.TestCase):
    """An author's repository, and a judge's home with its own clone, the request and the held-out answers."""

    def setUp(self):
        self.p = ScoredProject()
        self.p.set_local({})                      # the author's side names no private directory: it has none
        self.home = Path(tempfile.mkdtemp(prefix="morphogen-judge-home-"))
        self.clone = self.home / "projects" / "classify"
        self.clone.parent.mkdir()
        git(self.home, "clone", "-q", str(self.p.repo), str(self.clone))
        (self.home / "requests").mkdir()
        self.request = {"morphogen": "request/v1", "kind": "judge", "project": str(self.clone), "base": "main",
                        "target": "cell:classify",
                        "local": {"sandbox": SANDBOX, "cells": {"classify": {"private": str(self.p.private_dir)}}}}
        (self.home / "requests" / "classify.yaml").write_text(yaml.safe_dump(self.request))

    def tearDown(self):
        self.p.close()
        shutil.rmtree(self.home, ignore_errors=True)

    def bundle(self, *revs) -> io.BytesIO:
        r = subprocess.run(["git", "bundle", "create", "-", *revs], cwd=self.p.repo, check=True, capture_output=True)
        return io.BytesIO(r.stdout)

    def candidate(self, name, files) -> io.BytesIO:
        self.p.branch(name, {f"{self.p.home}/{k}": v for k, v in files.items()}, root=True)
        return self.bundle(name, "^main")

    def refs(self) -> str:
        return out(self.clone, "for-each-ref", "--format=%(refname) %(objectname)")


class IntakeRuns(Intake):
    def test_a_better_candidate_passes_and_the_verdict_is_the_judges(self):
        r = intake.judge(self.home, "classify", self.candidate("better", {"classify.py": BETTER}))
        self.assertEqual(r["verdict"], "pass", r)
        self.assertEqual(r["candidate"], out(self.p.repo, "rev-parse", "better"))
        self.assertEqual(len(Evidence.for_project(self.clone).dump()), 1)
        self.assertEqual(Evidence.for_project(self.p.repo).dump(), [])      # nothing is written on the author's side

    def test_a_candidate_with_its_whole_history_is_taken_too(self):
        self.p.branch("better", {f"{self.p.home}/classify.py": BETTER}, root=True)
        self.assertEqual(intake.judge(self.home, "classify", self.bundle("better"))["verdict"], "pass")

    def test_nothing_is_left_in_the_judges_clone(self):
        before = self.refs()
        intake.judge(self.home, "classify", self.candidate("better", {"classify.py": BETTER}))
        self.assertEqual(self.refs(), before)

    def test_the_owner_advances_the_base(self):
        self.p.on_main({"classify.py": BETTER})
        r = intake.advance(self.home, "classify", self.bundle("main"))
        self.assertEqual(r["base"], out(self.p.repo, "rev-parse", "main"))
        self.assertEqual(out(self.clone, "rev-parse", "main"), r["base"])
        self.assertEqual(out(self.clone, "status", "--porcelain"), "")

    def test_a_candidate_ahead_of_the_judges_base_says_so(self):
        self.p.on_main({"classify.py": BETTER})
        with self.assertRaises(intake.IntakeError) as e:
            intake.judge(self.home, "classify", self.candidate("next", {"classify.py": BETTER + "# again\n"}))
        self.assertIn("advance", str(e.exception))


class IntakeCheats(Intake):
    def refused(self, name, bundle, **kw):
        before = self.refs()
        with self.assertRaises(intake.IntakeError) as e:
            intake.judge(self.home, name, bundle, **kw)
        self.assertEqual(self.refs(), before, "a refused intake changed the judge's clone")
        return str(e.exception)

    def test_name_a_request_of_the_authors_own(self):
        # a request names the private directory and the rules' base: the author may pick one, never write one
        mine = Path(tempfile.mkdtemp(prefix="morphogen-author-"))
        try:
            (mine / "mine.yaml").write_text(yaml.safe_dump({**self.request, "base": "better"}))
            for name in (str(mine / "mine"), "../" * 8 + str(mine / "mine").lstrip("/"), "classify.yaml", "", ".",
                         "classify/../classify", "classify\n"):
                self.refused(name, self.candidate("better", {"classify.py": BETTER}))
        finally:
            shutil.rmtree(mine, ignore_errors=True)

    def test_move_the_judges_base_with_the_candidate(self):
        # weaker rules committed on main, and a bundle that carries main as well as the candidate
        self.p.on_main({"score.py": PERFECT_SCORER})
        self.p.branch("cand", {f"{self.p.home}/classify.py": CLASSIFY + "# same\n"}, root=True)
        self.assertIn("one", self.refused("classify", self.bundle("main", "cand")))

    def test_call_the_candidate_main(self):
        # one ref, named as the base is: it must not land on the judge's branch, and the rules stay the old ones
        self.p.on_main({"score.py": PERFECT_SCORER})
        base = out(self.clone, "rev-parse", "main")
        r = intake.judge(self.home, "classify", self.bundle("main"))
        self.assertEqual(r["verdict"], "fail", r)
        self.assertEqual(out(self.clone, "rev-parse", "main"), base)

    def test_send_something_that_is_not_a_bundle(self):
        self.refused("classify", io.BytesIO(b"#!/bin/sh\nrm -rf ~\n"))
        self.refused("classify", io.BytesIO(b""))

    def test_send_more_than_the_judge_will_hold(self):
        self.assertIn("larger", self.refused("classify", self.candidate("better", {"classify.py": BETTER}), limit=64))

    def test_rewind_the_judges_base(self):
        # advancing is the owner's, and only forward: a commit that is not ahead of the base is refused
        self.p.branch("side", {f"{self.p.home}/score.py": PERFECT_SCORER}, root=True)
        self.p.on_main({"classify.py": BETTER})
        intake.advance(self.home, "classify", self.bundle("main"))
        base = out(self.clone, "rev-parse", "main")
        for revs in (("side",), ("main~1",)):
            git(self.p.repo, "branch", "-f", "old", revs[0])
            with self.assertRaises(intake.IntakeError):
                intake.advance(self.home, "classify", self.bundle("old"))
            self.assertEqual(out(self.clone, "rev-parse", "main"), base)

    def test_a_request_that_already_names_a_candidate(self):
        # the judge's side made a mistake: a request with a candidate would judge that, not what was sent
        (self.home / "requests" / "classify.yaml").write_text(yaml.safe_dump({**self.request, "candidate": "main"}))
        self.assertIn("candidate", self.refused("classify", self.candidate("better", {"classify.py": BETTER})))

    def test_a_request_whose_project_is_the_authors(self):
        # the clone must be the judge's own: under its home, where the author cannot write
        (self.home / "requests" / "classify.yaml").write_text(yaml.safe_dump({**self.request, "project": str(self.p.repo)}))
        with self.assertRaises(intake.IntakeError) as e:
            intake.judge(self.home, "classify", self.candidate("better", {"classify.py": BETTER}))
        self.assertIn("home", str(e.exception))


if __name__ == "__main__":
    unittest.main()
