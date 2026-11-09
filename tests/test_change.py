"""Judging a change that claims no improvement (judge.judge_change): no measure and no target, only the
base's rules. The cells a change belongs to come from the files it changes; it passes when every file
belongs to a cell that may change it and the tests of every interface those cells touch, and the cells'
own tests, pass on the candidate. The cheats are in test_redteam.ChangeCheats."""

import unittest

from tests.fixture_cells import CellsProject
from tests.fixture_scored import CLASSIFY


class JudgeAChange(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = CellsProject(code=True)
        cls.honest = cls.p.change(cls.p.branch("honest", {
            "classify/classify.py": CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 50") + "LIMIT = 100\n"}))

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def test_an_honest_change_passes(self):
        self.assertEqual(self.honest["verdict"], "pass", self.honest)
        self.assertEqual(self.honest["reasons"], [])

    def test_the_cells_come_from_the_files(self):
        self.assertEqual(self.honest["cells"], ["classify"])
        self.assertEqual(self.honest["files"], {"classify/classify.py": ["classify"]})

    def test_it_runs_the_cells_tests_and_every_touched_interfaces_tests(self):
        ran = {(t.get("interface") or t.get("cell"), t["test"]) for t in self.honest["tests"]}
        self.assertIn(("labels", "python -m unittest -q contracts.test_labels"), ran)
        self.assertIn(("classify", "python -m unittest -q test_classify"), ran)
        self.assertTrue(all(t["passed"] for t in self.honest["tests"]), self.honest["tests"])

    def test_it_is_recorded_as_a_verdict_on_the_change(self):
        rec = self.p.evidence.dump()[self.honest["evidence_seq"] - 1]
        self.assertEqual((rec["kind"], rec["verdict"], rec["by"]), ("verdict", "pass", "judge"))
        self.assertEqual(rec["subject"]["path"], "change")
        self.assertEqual(rec["cells"], ["classify"])
        self.assertEqual(rec["gate"]["decision"], "review")   # a pass allows what autonomy says; a person here

    def test_a_change_that_touches_nothing_is_refused(self):
        with self.assertRaises(Exception):
            self.p.change("main")


if __name__ == "__main__":
    unittest.main()
