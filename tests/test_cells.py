"""The cell format (morphogen.yaml): parsing, compiling, and default deny. A candidate may change only
what the judged cell's scope names in `change`; everything else is the judge's."""

from pathlib import Path
import unittest

import yaml

from morphogen import judge as judge_mod
from morphogen import optimize as O
from morphogen import project as P
from morphogen.structure import Structure
from tests.fixture_cells import CELLS_CONTRACT, CellsProject, cells_doc
from tests.fixture_scored import CLASSIFY, CLASSIFY_BENCH

BETTER = CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 50")


class Parse(unittest.TestCase):
    def test_change_forms(self):
        self.assertEqual(P.parse_change("src/**"), {"path": "src/**"})
        self.assertEqual(P.parse_change("a.py#N in 0..100"), {"path": "a.py", "name": "N", "range": [0.0, 100.0]})
        self.assertEqual(P.parse_change("a.py#MODE in [fast, slow]"),
                         {"path": "a.py", "name": "MODE", "choices": ["fast", "slow"]})
        self.assertEqual(P.parse_change("conf.yaml:model.temperature in 0..1.5"),
                         {"path": "conf.yaml", "key": "model.temperature", "range": [0.0, 1.5]})
        self.assertEqual(P.parse_change("a.py#N"), {"path": "a.py", "name": "N"})
        for bad in ("", "a.py#N in 5..1", "a.py#N in nonsense", "/etc/passwd", "../x.py", "a.py#"):
            with self.assertRaises(P.ProjectError, msg=bad):
                P.parse_change(bad)

    def test_better_forms(self):
        self.assertEqual(P.parse_better("wall_seconds lower"),
                         {"wall_seconds": {"direction": "lower", "primary": True}})
        m = P.parse_better("accuracy higher, wall_seconds lower", scored=True)
        self.assertEqual(list(m), ["scored.accuracy", "wall_seconds"])
        self.assertTrue(m["scored.accuracy"]["primary"])
        self.assertFalse(m["wall_seconds"]["primary"])
        m = P.parse_better({"accuracy": {"higher": True, "min": 0.05, "gain": "absolute"}}, scored=True)
        self.assertEqual(m["scored.accuracy"], {"direction": "higher", "primary": True, "min_improvement": 0.05,
                                                "gain": "absolute"})
        with self.assertRaises(P.ProjectError):
            P.parse_better("accuracy sideways")

    def test_compile_structure_and_spec(self):
        proj = P.Project.from_dict(cells_doc())
        s = proj.structure()
        self.assertEqual(s.cells["classify"].parent, "app")
        self.assertEqual(s.providers("labels"), ["classify"])
        self.assertEqual(s.interfaces["labels"].tests, ["python -m unittest -q contracts.test_labels"])
        self.assertEqual(s.cells["classify"].parameters["THRESHOLD"].range, (0.0, 100.0))
        spec = proj.spec("classify", local={"private": "/elsewhere"})
        self.assertEqual(spec["measure"]["run"], "python bench.py")
        self.assertEqual(spec["measure"]["score"], {"run": "python score.py", "private": "/elsewhere"})
        self.assertFalse(spec["measure"]["same_output"])          # scored output may differ
        self.assertEqual(spec["check"], "python -m unittest -q test_classify")
        self.assertIn("scored.accuracy", spec["measure"]["metrics"])
        with self.assertRaises(P.ProjectError):
            proj.spec("report")                                     # no run: nothing to measure

    def test_unknown_fields_are_refused(self):
        d = cells_doc()
        d["cells"]["classify"]["chnage"] = "x.py"
        with self.assertRaises(P.ProjectError):
            P.Project.from_dict(d)

    def test_tests_only_from_the_base_and_the_project_file_is_never_changeable(self):
        d = cells_doc()
        d["cells"]["classify"]["change"] = "**"
        proj = P.Project.from_dict(d)
        self.assertFalse(proj.allows(["classify"], "morphogen.yaml"))
        self.assertTrue(proj.allows(["classify"], "classify/bench.py"))


class Passes(unittest.TestCase):
    """The honest changes pass, so the cheats below fail for the right reason."""

    def test_tune_the_setting(self):
        p = CellsProject()
        try:
            r = p.judge(p.branch("t50", {"classify/classify.py": BETTER}))
            self.assertEqual(r["verdict"], "pass", r)
            self.assertEqual(r["cell"], "classify")
            self.assertEqual(r["parameters"]["classify.THRESHOLD"]["candidate"], 50)
            self.assertEqual([x["interface"] for x in r["interfaces"]], ["labels"])
        finally:
            p.close()

    def test_change_the_code(self):
        p = CellsProject(code=True)
        try:
            better = BETTER.replace('return "high" if x >= THRESHOLD else "low"',
                                    'return "low" if x < THRESHOLD else "high"') + "LIMIT = 100\n"
            r = p.judge(p.branch("code", {"classify/classify.py": better}))
            self.assertEqual(r["verdict"], "pass", r)
        finally:
            p.close()


class DefaultDenyCheats(unittest.TestCase):
    """Each candidate scores better (THRESHOLD 50 or labels from the answers) and must still fail."""

    @classmethod
    def setUpClass(cls):
        cls.p = CellsProject()
        cls.code = CellsProject(code=True)

    @classmethod
    def tearDownClass(cls):
        cls.p.close()
        cls.code.close()

    def assertRefused(self, p, name, word, **change):
        r = p.judge(p.branch(name, **change))
        self.assertEqual(r["verdict"], "fail", f"cheat {name!r} passed the judge: {r}")
        self.assertTrue(any(word in x for x in r["reasons"]), r["reasons"])
        return r

    def test_edit_a_file_outside_change(self):
        rigged = CLASSIFY_BENCH.replace("print(label(x))", 'print("high" if x >= 50 else "low")')
        self.assertRefused(self.p, "rig-bench", "outside", files={"classify/bench.py": rigged})

    def test_add_a_new_file(self):
        self.assertRefused(self.p, "new-file", "outside",
                           files={"classify/classify.py": BETTER, "classify/helper.py": "X = 1\n"})

    def test_delete_a_test(self):
        self.assertRefused(self.p, "delete-test", "outside",
                           files={"classify/classify.py": BETTER}, delete=["classify/test_classify.py"])

    def test_weaken_the_contract(self):
        weak = CELLS_CONTRACT.replace("(-5, 0, 3.5, 49, 50, 1000)", "(0, 50)")
        self.assertRefused(self.p, "weak-contract", "outside",
                           files={"classify/classify.py": BETTER, "contracts/test_labels.py": weak})

    def test_widen_change_in_the_candidates_own_project_file(self):
        d = cells_doc()
        d["cells"]["classify"]["change"] = "classify/**"
        rigged = CLASSIFY_BENCH.replace("print(label(x))", 'print("high" if x >= 50 else "low")')
        self.assertRefused(self.p, "widen", "outside",
                           files={"morphogen.yaml": yaml.safe_dump(d), "classify/bench.py": rigged})

    def test_change_more_than_the_setting(self):
        rigged = BETTER.replace('def label(x):\n', 'def label(x):\n    x = x + 0\n')
        self.assertRefused(self.p, "more-than-setting", "only", files={"classify/classify.py": rigged})

    def test_setting_out_of_range(self):
        self.assertRefused(self.p, "out-of-range", "range",
                           files={"classify/classify.py": CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 500")})

    def test_change_a_kept_setting(self):
        self.assertRefused(self.code, "kept", "LIMIT",
                           files={"classify/classify.py": BETTER + "LIMIT = 5\n"})

    def test_symlink_out_of_change(self):
        # classify.py becomes a link to the answers: the code reads them through a path it may change
        self.assertRefused(self.code, "link-out", "link",
                           links={"classify/classify.py": str(self.code.private_dir / "gold.json")})

    def test_add_a_symlink_to_the_answers(self):
        reader = BETTER.replace('def label(x):\n', 'import json as _j\nG = _j.load(open("g.json"))\n\ndef label(x):\n')
        self.assertRefused(self.code, "link-add", "outside", files={"classify/classify.py": reader + "LIMIT = 100\n"},
                           links={"classify/g.json": str(self.code.private_dir / "gold.json")})

    def test_break_a_neighbours_contract(self):
        broken = BETTER.replace('def label(x):\n', 'def label(x):\n    if x < 0:\n        raise ValueError\n')
        self.assertRefused(self.code, "break-contract", "interface",
                           files={"classify/classify.py": broken + "LIMIT = 100\n"})


class Paths(unittest.TestCase):
    """probe, measure, tune and the structure tools on the cell format."""

    @classmethod
    def setUpClass(cls):
        cls.p = CellsProject(search=True)

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def test_names(self):
        self.assertEqual(judge_mod.cell_of(self.p.repo, Path("classify")), "classify")
        r = self.p.judge(self.p.branch("by-name", {"classify/classify.py": BETTER}), target="classify")
        self.assertEqual(r["cell"], "classify")
        with self.assertRaises(judge_mod.JudgeError):
            self.p.judge("by-name", target="cell:report")       # no run

    def test_structure_tools_read_the_project_file(self):
        s = Structure.load(self.p.repo / "morphogen.yaml")
        self.assertEqual(sorted(s.cells), ["app", "classify", "report"])
        self.assertEqual(s.coverage()["tested"], 1)

    def test_measure_and_probe(self):
        m = judge_mod.measure(self.p.repo, self.p.cfg, "cell:classify", "main", self.p.evidence)
        self.assertIn("scored.accuracy", m["metrics"])
        rec = self.p.evidence.query(where={"kind": "measurement"}, limit=1)[0]
        self.assertEqual(rec["subject"]["path"], "cell:classify")
        pr = judge_mod.probe(self.p.repo, self.p.cfg, "cell:classify", self.p.branch("p50", {"classify/classify.py": BETTER}),
                             self.p.evidence, cases=0, rounds=1)
        self.assertEqual(pr["cell"], "classify")
        self.assertTrue(all(x["passed"] for x in pr["interfaces"]))
        self.assertGreater(pr["metrics"]["scored.accuracy"]["gain"], 0)
        pr = judge_mod.probe(self.p.repo, self.p.cfg, "cell:classify",
                             self.p.branch("p-rig", {"classify/bench.py": "print('x')\n"}), self.p.evidence, cases=0, rounds=0)
        self.assertTrue(any("outside" in x for x in pr["forbidden"]), pr)

    def test_tune_finds_the_threshold(self):
        r = O.tune(self.p.repo, self.p.cfg, "cell:classify", O.make("hillclimb", trials=20), self.p.evidence,
                   rounds=1, max_trials=20)
        self.assertEqual(r["verdict"], "pass", r.get("note") or r.get("judge"))
        self.assertIn(r["best"]["values"]["classify.THRESHOLD"], (49, 50, 51))
        self.assertEqual(r["target"], "cell:classify")
        self.assertTrue(O.prior_from_evidence(self.p.evidence, "cell:classify"))


if __name__ == "__main__":
    unittest.main()
