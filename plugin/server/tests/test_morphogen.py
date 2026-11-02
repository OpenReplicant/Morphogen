"""Conformance of the files backend, and the judge's ordinary behaviour on the sample target."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from morphogen import judge as judge_mod
from morphogen import project
from morphogen.backend_files import FilesEvidenceLog, FilesListStore

from tests.fixture import FAST, TARGET, SampleProject

WRONG = FAST.replace("(-p[1], p[0])", "(-p[1], len(p[0]))")  # breaks alphabetical tie order


class Conformance(unittest.TestCase):
    """What every backend must do. Run against each backend that exists."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_lists_put_get_query_follow_dump_load(self):
        s = FilesListStore(self.tmp / "lists")
        s.put("systems", {"id": "sys", "slots": ["sys/a"]})
        s.put("slots", {"id": "sys/a", "accepts": ["type/x"], "filled_by": "comp/c"})
        s.put("types", {"id": "type/x"})
        s.put("components", {"id": "comp/c", "type": "type/x", "tags": ["fast"]})
        self.assertEqual(s.get("types", "type/x"), {"id": "type/x"})
        self.assertEqual([e["id"] for e in s.query("components", {"tags": "fast"})], ["comp/c"])
        self.assertEqual([e["id"] for e in s.query("slots", {"accepts": "~type/"})], ["sys/a"])
        self.assertEqual([e["id"] for e in s.follow("systems", "sys", "slots", 1)], ["sys/a"])
        dump = s.dump()
        other = FilesListStore(self.tmp / "copy")
        other.load(dump)
        self.assertEqual(other.dump(), dump)
        with self.assertRaises(ValueError):
            s.put("nonsense", {"id": "x"})
        with self.assertRaises(ValueError):
            s.put("types", {"name": "no id"})

    def test_evidence_append_only_and_tamper_evident(self):
        log = FilesEvidenceLog(self.tmp / "evidence.jsonl")
        log.append({"claim": "a", "trust": "measured", "by": "judge"})
        log.append({"claim": "b", "trust": "inferred", "by": "agent"})
        self.assertEqual(log.verify(), (True, None))
        self.assertEqual([r["claim"] for r in log.query()], ["b", "a"])
        with self.assertRaises(ValueError):
            log.append({"claim": "c", "trust": "certain", "by": "agent"})
        lines = log.path.read_text().splitlines()
        rec = json.loads(lines[0])
        rec["claim"] = "rewritten"
        lines[0] = json.dumps(rec)
        log.path.write_text("\n".join(lines) + "\n")
        self.assertEqual(log.verify(), (False, 1))


class JudgeOnSample(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = SampleProject()

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def test_faster_and_correct_passes(self):
        r = self.p.judge(self.p.branch("fast", {"topwords.py": FAST}))
        self.assertEqual(r["verdict"], "pass", r)
        self.assertGreater(r["metrics"]["wall_seconds"]["gain"], 0.5)
        self.assertGreater(r["metrics"]["wall_seconds"]["ci95"][0], 0)

    def test_wrong_tie_order_fails(self):
        r = self.p.judge(self.p.branch("wrong", {"topwords.py": WRONG}))
        self.assertEqual(r["verdict"], "fail", r)

    def test_no_change_fails(self):
        r = self.p.judge(self.p.branch("same", {"README": "no code change\n"}))
        self.assertEqual(r["verdict"], "fail", r)

    def test_verdicts_are_measured_evidence_with_seeds(self):
        self.p.judge(self.p.branch("fast2", {"topwords.py": FAST}))
        recs = self.p.evidence.query(by="judge")
        self.assertTrue(recs and all(r["trust"] == "measured" for r in recs))
        self.assertTrue(recs[0]["seeds"]["equivalence"])
        self.assertEqual(self.p.evidence.verify(), (True, None))

    def test_evidence_survives_candidate_commits_and_branch_switches(self):
        before = len(self.p.evidence.dump())
        self.p.judge(self.p.branch("fast3", {"topwords.py": FAST}))
        self.p.branch("unrelated", {"notes.txt": "x\n"})  # commits with `git add -A`
        self.assertEqual(len(self.p.evidence.dump()), before + 1)
        self.assertIn("/.git/", str(self.p.evidence.path))

    def test_measure_records_baseline(self):
        r = judge_mod.measure(self.p.repo, self.p.cfg, TARGET, "main", self.p.evidence)
        self.assertIn("wall_seconds", r["metrics"])

    def test_doctor_reports_guarantees(self):
        d = project.doctor(self.p.repo)
        self.assertEqual(d["evidence"]["chain"], "intact")
        self.assertIn("timing", d["guarantees"])


class TrialBudget(unittest.TestCase):
    def test_budget_stops_judging(self):
        p = SampleProject(trials_per_day=1)
        try:
            p.judge(p.branch("wrong", {"topwords.py": WRONG}))
            with self.assertRaises(judge_mod.JudgeError):
                p.judge(p.branch("fast", {"topwords.py": FAST}))
        finally:
            p.close()


if __name__ == "__main__":
    unittest.main()
