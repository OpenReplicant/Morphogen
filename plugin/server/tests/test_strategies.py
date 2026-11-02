"""The strategy catalog, the archive, payoff and auto selection."""

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from morphogen import strategies as S
from morphogen.backend_files import FilesEvidenceLog

from tests.fixture import FAST, TARGET, SampleProject

T = "targets/x"


def verdict(log, n, strategy, ok, gain=0.2, parent=None):
    labels = {"strategy": strategy}
    if parent:
        labels["parent"] = parent
    log.append({"claim": f"trial {n}", "kind": "verdict", "verdict": "pass" if ok else "fail",
                "subject": {"system": "x", "path": T},
                "outcome": {"metrics": {"wall_seconds": {"primary": True, "gain": gain if ok else 0.01}}},
                "refs": {"base": "b" * 40, "candidate": f"{n:040d}"}, "labels": labels,
                "trust": "measured", "by": "judge"})


class Selection(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=self.tmp, check=True)
        (self.tmp / T).mkdir(parents=True)
        self.log = FilesEvidenceLog(self.tmp / "evidence.jsonl")
        self.cfg = {"strategy": "auto", "trunk": "main"}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def choose(self):
        return S.choose(self.tmp, self.cfg, self.log, T)

    def test_catalog_ships_three_cards(self):
        cards = S.catalog(self.tmp)
        self.assertTrue({"hill-climb", "archive-search", "simplify"} <= set(cards))
        self.assertTrue(all(c["body"] and c["description"] for c in cards.values()))

    def test_project_card_is_added_to_the_catalog(self):
        (self.tmp / "strategies").mkdir()
        (self.tmp / "strategies" / "beam.md").write_text("---\nname: beam\ndescription: d\nwhen: w\n---\nbody\n")
        self.assertIn("beam", S.catalog(self.tmp))

    def test_no_trials_starts_with_hill_climb(self):
        self.assertEqual(self.choose()["strategy"], "hill-climb")

    def test_hill_climb_stall_switches_to_archive_search(self):
        for n in range(4):
            verdict(self.log, n, "hill-climb", False)
        r = self.choose()
        self.assertEqual(r["strategy"], "archive-search", r["reason"])
        self.assertIn("Parent", r["card"])

    def test_both_stalled_means_stop(self):
        for n in range(4):
            verdict(self.log, n, "hill-climb", False)
        for n in range(4, 8):
            verdict(self.log, n, "archive-search", False)
        self.assertEqual(self.choose()["strategy"], "stop")

    def test_a_pass_resets_the_stall(self):
        for n in range(3):
            verdict(self.log, n, "hill-climb", False)
        verdict(self.log, 3, "hill-climb", True)
        self.assertEqual(self.choose()["strategy"], "hill-climb")

    def test_bandit_prefers_higher_gain_per_trial(self):
        for n in range(4):
            verdict(self.log, n, "hill-climb", n == 0, gain=0.15)
        for n in range(4, 8):
            verdict(self.log, n, "archive-search", n < 7, gain=0.30)
        r = self.choose()
        self.assertEqual(r["strategy"], "archive-search", r["reason"])
        self.assertGreater(r["payoff"]["archive-search"]["gain_per_trial"],
                           r["payoff"]["hill-climb"]["gain_per_trial"])

    def test_setting_forces_a_strategy(self):
        self.cfg["strategy"] = "simplify"
        self.assertEqual(self.choose()["strategy"], "simplify")
        self.cfg["strategies"] = {T: "archive-search"}
        self.assertEqual(self.choose()["strategy"], "archive-search")


class WithJudge(unittest.TestCase):
    """Labels reach the archive, and a large unmerged pass triggers simplify once."""

    @classmethod
    def setUpClass(cls):
        cls.p = SampleProject()

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def test_labels_lineage_and_simplify(self):
        padding = "".join(f"# note {i}: an incidental comment that a smaller change would drop\n" for i in range(30))
        big = self.p.branch("big", {"topwords.py": FAST + padding})
        from morphogen import judge as J
        res = J.judge(self.p.repo, self.p.cfg, TARGET, "main", big, self.p.evidence,
                      {"strategy": "hill-climb", "family": "hash-count"})
        self.assertEqual(res["verdict"], "pass", res)

        variants = S.archive(self.p.evidence, TARGET)
        self.assertEqual(variants[-1]["strategy"], "hill-climb")
        self.assertEqual(variants[-1]["family"], "hash-count")

        choice = S.choose(self.p.repo, self.p.cfg, self.p.evidence, TARGET)
        self.assertEqual(choice["strategy"], "simplify", choice["reason"])

        small = self.p.branch("small", {"topwords.py": FAST})
        J.judge(self.p.repo, self.p.cfg, TARGET, "main", small, self.p.evidence,
                {"strategy": "simplify", "parent": res["candidate"][:12]})
        choice = S.choose(self.p.repo, self.p.cfg, self.p.evidence, TARGET)
        self.assertNotEqual(choice["strategy"], "simplify", choice["reason"])


if __name__ == "__main__":
    unittest.main()
