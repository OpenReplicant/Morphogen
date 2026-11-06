"""The judge on sample targets: verdicts, measurement, probes, parameters, scoring outside the candidate,
and the evidence log."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from morphogen import documents
from morphogen import judge as judge_mod
from morphogen.evidence import Evidence
from tests.fixture import (CLASSIFY, COMPUTE, FAST, SETTINGS, TARGET, WRONG, GuardedProject, InputsProject,
                           SampleProject, ScoredProject, StructuredProject, git, parameter_project)


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

    def test_wrong_output_fails(self):
        self.assertEqual(self.p.judge(self.p.branch("wrong", {"topwords.py": WRONG}))["verdict"], "fail")

    def test_no_change_fails(self):
        self.assertEqual(self.p.judge(self.p.branch("same", {"README": "no code change\n"}))["verdict"], "fail")

    def test_verdicts_are_measured_evidence_with_seeds(self):
        self.p.judge(self.p.branch("fast2", {"topwords.py": FAST}))
        recs = self.p.evidence.query(by="judge")
        self.assertTrue(recs and all(r["trust"] == "measured" for r in recs))
        self.assertTrue(recs[0]["seeds"]["equivalence"])
        self.assertEqual(self.p.evidence.verify(), (True, None))
        self.assertIn("/.git/", str(self.p.evidence.path))

    def test_measure_records_baseline(self):
        r = judge_mod.measure(self.p.repo, self.p.cfg, TARGET, "main", self.p.evidence)
        self.assertIn("wall_seconds", r["metrics"])

    def test_probe_gives_feedback_not_a_verdict(self):
        r = judge_mod.probe(self.p.repo, self.p.cfg, TARGET, self.p.branch("wrong-probe", {"topwords.py": WRONG}),
                            self.p.evidence, rounds=0)
        self.assertTrue([c for c in r["cases"] if c["status"] == "wrong"])

    def test_the_judge_refuses_a_malformed_cell(self):
        doc = self.p.doc()
        doc["cells"]["slow-script"]["better"] = {"wall_seconds": {"lower": True, "gain": "huge"}}
        cand = self.p.branch("malformed-base", {"morphogen.yaml": self.p.dump(doc)}, root=True)
        with self.assertRaises(judge_mod.JudgeError):
            self.p.judge("main", base=cand)


class Parameters(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = parameter_project()

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def test_a_tune_run_records_the_values_in_its_verdict(self):
        tuned = FAST + SETTINGS.replace("CHUNK = 64", "CHUNK = 128")
        r = self.p.judge(self.p.branch("tune-chunk", {"topwords.py": tuned}), {"optimizer": "grid"})
        self.assertEqual(r["verdict"], "pass", r)
        self.assertEqual(r["parameters"]["slow-script.CHUNK"], {"owner": "agent", "base": 64, "candidate": 128})
        rec = self.p.evidence.query(by="judge", limit=1)[0]
        self.assertEqual(rec["labels"]["optimizer"], "grid")

    def test_a_setting_needs_exactly_one_location(self):
        from pydantic import ValidationError
        from morphogen.structure import Parameter
        with self.assertRaises(ValidationError):
            Parameter(file="a.py", owner="agent")
        with self.assertRaises(ValidationError):
            Parameter(file="a.py", name="A", key="a", owner="agent")


class Scored(unittest.TestCase):
    """Accuracy scored outside the candidate, against held-out answers outside the repository."""

    @classmethod
    def setUpClass(cls):
        cls.p = ScoredProject()

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def test_a_better_setting_passes_on_the_scored_metric(self):
        r = self.p.judge(self.p.branch("t50", {"classify.py": CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 50")}))
        self.assertEqual(r["verdict"], "pass", r)
        self.assertAlmostEqual(r["metrics"]["scored.accuracy"]["candidate"], 1.0)
        self.assertEqual(r["parameters"]["classify.THRESHOLD"]["candidate"], 50)

    def test_a_worse_setting_fails(self):
        r = self.p.judge(self.p.branch("t90", {"classify.py": CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 95")}))
        self.assertEqual(r["verdict"], "fail", r)

    def test_identical_code_does_not_pass(self):
        r = self.p.judge(self.p.branch("same-score", {"classify.py": CLASSIFY + "# no change\n"}))
        self.assertEqual(r["verdict"], "fail", r)

    def test_measure_reports_the_score(self):
        r = judge_mod.measure(self.p.repo, self.p.cfg, self.p.target, "main", self.p.evidence)
        self.assertLess(r["metrics"]["scored.accuracy"], 0.7)

    def test_a_private_directory_inside_the_repository_is_refused(self):
        q = ScoredProject(private_inside=True)
        try:
            with self.assertRaises(judge_mod.JudgeError) as e:
                q.judge(q.branch("t50", {"classify.py": CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 50")}))
            self.assertIn("outside the repository", str(e.exception))
        finally:
            q.close()

    def test_inputs_outside_the_repository(self):
        # The workload reads its data from MORPHOGEN_INPUTS (morphogen.local.yaml's `inputs`); the
        # verdict and the measurement record a digest of what it read.
        q = InputsProject()
        try:
            m = judge_mod.measure(q.repo, q.cfg, q.target, "main", q.evidence)
            self.assertLess(m["metrics"]["scored.accuracy"], 0.7)
            r = q.judge(q.branch("t50", {"classify.py": CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 50")}))
            self.assertEqual(r["verdict"], "pass", r)
            digests = {rec.get("inputs") for rec in q.evidence.query(by="judge")}
            self.assertEqual(digests, {judge_mod.inputs_digest(q.inputs_dir)})
        finally:
            q.close()

    def test_a_target_that_requires_isolation_is_refused_without_it(self):
        spec = documents.validate("target", {"requires": ["network_isolated", "private_paths_hidden"]})
        with self.assertRaises(judge_mod.JudgeError) as e:
            judge_mod._check_runner(spec, {"sandbox": "none"})
        self.assertIn("network_isolated", str(e.exception))
        judge_mod._check_runner(documents.validate("target", {}), {"sandbox": "none"})
        with self.assertRaises(documents.DocumentError):
            documents.validate("target", {"requires": ["magic"]})

    def test_a_scored_primary_needs_a_scorer(self):
        spec = documents.validate("target", {"measure": {"run": "x", "metrics": {
            "scored.accuracy": {"direction": "higher", "primary": True}}}})
        with self.assertRaises(judge_mod.JudgeError):
            judge_mod._check_spec(spec)


class CellGate(unittest.TestCase):
    """Judging a cell runs the tests of every interface its scope touches, from the base's structure."""

    @classmethod
    def setUpClass(cls):
        cls.p = StructuredProject()

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def test_a_change_that_keeps_its_interfaces_passes(self):
        better = CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 50")
        r = self.p.judge_cell(self.p.branch_files("ok-cell", {"targets/classify/classify.py": better}))
        self.assertEqual(r["verdict"], "pass", r)
        self.assertEqual(r["cell"], "classify")
        self.assertEqual([(x["interface"], x["passed"]) for x in r["interfaces"]], [("labels", True)])
        rec = self.p.evidence.query(by="judge", where={"kind": "verdict"}, limit=1)[0]
        self.assertEqual(rec["scope"], ["classify"])
        self.assertEqual(rec["outcome"]["interfaces"][0]["interface"], "labels")

    def test_naming_the_directory_judges_the_cell_that_measures_it(self):
        better = CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 50")
        r = self.p.judge(self.p.branch_files("by-path", {"targets/classify/classify.py": better}))
        self.assertEqual(r["cell"], "classify")
        self.assertEqual([(x["interface"], x["passed"]) for x in r["interfaces"]], [("labels", True)])

    def test_a_directory_no_cell_runs_in_is_an_error(self):
        with self.assertRaises(judge_mod.JudgeError):
            self.p.judge("main", target="contracts")

    def test_probe_reports_interface_tests(self):
        broken = CLASSIFY.replace("def label(x):\n", "def label(x):\n    if x < 0:\n        raise ValueError\n")
        r = judge_mod.probe(self.p.repo, self.p.cfg, self.p.target,
                            self.p.branch_files("probe-cell", {"targets/classify/classify.py": broken}),
                            self.p.evidence, cases=0, rounds=0, cell="classify")
        self.assertFalse(r["interfaces"][0]["passed"])
        self.assertIn("output", r["interfaces"][0])

    def test_settings_are_recorded_searched_and_counted_once(self):
        from morphogen.optimize import space_of
        doc = self.p.doc()
        doc["cells"]["classify"]["change"] += ["targets/classify/classify.py#MARGIN in [0, 1, 2]",
                                               "targets/classify/classify.py#THRESHOLD in 0..100"]   # twice
        base = self.p.branch_files("cell-params", {"morphogen.yaml": self.p.dump(doc),
                                                   "targets/classify/classify.py": CLASSIFY + "MARGIN = 0\n"})
        git(self.p.repo, "checkout", "-q", base)
        try:
            space = space_of(self.p.repo, "classify")
        finally:
            git(self.p.repo, "checkout", "-q", "main")
        self.assertEqual(sorted(k for k, v in space.items() if v["_kind"] != "text"),
                         ["classify.MARGIN", "classify.THRESHOLD"])
        self.assertEqual(space["classify.targets/classify/classify.py"]["_kind"], "text")   # the whole file
        self.assertEqual(space["classify.MARGIN"]["_value"], 0)
        cand = self.p.branch_files("cell-params-cand", {"targets/classify/classify.py":
                                                        CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 50") + "MARGIN = 1\n"},
                                   base=base)
        r = self.p.judge(cand, base=base)
        self.assertEqual(r["parameters"]["classify.MARGIN"], {"owner": "agent", "base": 0, "candidate": 1})
        self.assertEqual(sorted(r["parameters"]), ["classify.MARGIN", "classify.THRESHOLD"])

    def test_an_unknown_cell_is_an_error(self):
        with self.assertRaises(judge_mod.JudgeError):
            self.p.judge_cell("main", cell="nope")


class SystemGuard(unittest.TestCase):
    """Judging a cell also measures the system around it (its topmost ancestor with a measure)."""

    @classmethod
    def setUpClass(cls):
        cls.p = GuardedProject()

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    FASTER = COMPUTE.replace("def fast_path(n):\n    return sum(i * i for i in range(n))",
                             "def fast_path(n):\n    return n * (n - 1) * (2 * n - 1) // 6")

    def test_a_cell_speedup_that_helps_the_system_passes(self):
        r = self.p.judge_cell(self.p.branch_root("faster", {"targets/system/compute.py": self.FASTER}))
        self.assertEqual(r["verdict"], "pass", r)
        self.assertEqual((r["system"]["cell"], r["system"]["target"]), ("system", "cell:system"))
        self.assertTrue(r["system"]["ok"])
        self.assertFalse(r["system"]["metrics"]["wall_seconds"]["primary"])   # a constraint, not the goal
        rec = self.p.evidence.query(by="judge", where={"kind": "verdict"}, limit=1)[0]
        self.assertEqual(rec["outcome"]["system"]["cell"], "system")

    def test_no_guard_when_turned_off(self):
        doc = self.p.doc()
        doc["cells"]["fast"]["guard"] = False
        base = self.p.branch_root("no-guard-base", {"morphogen.yaml": self.p.dump(doc)})
        cand = self.p.branch_root("faster-3", {"targets/system/compute.py": self.FASTER}, base=base)
        self.assertIsNone(self.p.judge(cand, base=base)["system"])


class Tune(unittest.TestCase):
    """An optimizer proposes values for agent-owned parameters; probes score them against the search
    answers; only the best goes to the judge, which scores it on the held-out answers."""

    @classmethod
    def setUpClass(cls):
        cls.p = ScoredProject(search=True)

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def test_grid_finds_the_threshold_and_the_judge_passes_it(self):
        from morphogen.optimize import Grid, tune
        r = tune(self.p.repo, self.p.cfg, self.p.target, Grid(steps=5), self.p.evidence, rounds=1)
        self.assertEqual(r["best"]["values"], {"classify.THRESHOLD": 50}, r["trials"])
        self.assertEqual(r["verdict"], "pass", r.get("judge"))
        self.assertEqual(len(r["trials"]), 5)                       # 0, 25, 50, 75, 100
        verdict = self.p.evidence.query(by="judge", where={"kind": "verdict"}, limit=1)[0]
        self.assertEqual(verdict["labels"]["optimizer"], "grid")
        probes = [r for r in self.p.evidence.dump() if r.get("kind") == "probe"]
        self.assertGreaterEqual(len(probes), 4)

    def test_probes_score_against_the_search_answers(self):
        spec = {"measure": {"score": {"run": "x", "private": str(self.p.private_dir), "search": str(self.p.search_dir)}}}
        judge_mod._prepare_score(spec, self.p.repo, "probe")
        self.assertEqual(spec["measure"]["score"]["private"], str(self.p.search_dir.resolve()))
        spec = {"measure": {"score": {"run": "x", "private": str(self.p.private_dir), "search": str(self.p.search_dir)}}}
        judge_mod._prepare_score(spec, self.p.repo)
        self.assertEqual(spec["measure"]["score"]["private"], str(self.p.private_dir.resolve()))

    def test_writing_a_parameter_is_read_back_the_same_way(self):
        from morphogen.optimize import write_parameter
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "m.py").write_text("A = 1\nB: int = 2\nA = 3\n")
            (d / "c.yaml").write_text("x:\n  y: 1\n")
            write_parameter(d, {"file": "m.py", "name": "A"}, 7)
            write_parameter(d, {"file": "m.py", "name": "B"}, 8)
            write_parameter(d, {"file": "c.yaml", "key": "x.y"}, 0.5)
            self.assertEqual(judge_mod._read_parameter(d, {"file": "m.py", "name": "A"}), 7)
            self.assertEqual(judge_mod._read_parameter(d, {"file": "m.py", "name": "B"}), 8)
            self.assertEqual(judge_mod._read_parameter(d, {"file": "c.yaml", "key": "x.y"}), 0.5)


class CommandLine(unittest.TestCase):
    def test_judge_tune_and_evidence_from_the_command_line(self):
        import subprocess
        import sys
        p = ScoredProject(search=True)
        try:
            doc = p.doc()
            doc["cells"]["classify"]["provides"] = "labels"
            doc["interfaces"] = {"labels": {"tests": "cd targets/classify && python -m unittest -q test_classify",
                                            "external": "consumes"}}
            p.on_main(doc=doc)

            def cli(*args):
                return subprocess.run([sys.executable, "-m", "morphogen", *args], cwd=p.repo,
                                      capture_output=True, text=True)
            branch = p.branch("t50", {"classify.py": CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 50")})
            r = cli("judge", "cell:classify", branch)
            self.assertEqual(r.returncode, 0, r.stderr + r.stdout)
            self.assertEqual(json.loads(r.stdout)["verdict"], "pass")
            r = cli("tune", "cell:classify", "--optimizer", "grid", "--steps", "3", "--rounds", "1")
            self.assertEqual(json.loads(r.stdout)["best"]["values"], {"classify.THRESHOLD": 50}, r.stderr)
            r = cli("evidence", "--verify")
            self.assertEqual(json.loads(r.stdout)["chain"], "intact")
            r = cli("judge", "cell:nope", branch)
            self.assertEqual(r.returncode, 2)
        finally:
            p.close()


class EvidenceLog(unittest.TestCase):
    def test_append_verify_and_tamper(self):
        with tempfile.TemporaryDirectory() as d:
            ev = Evidence(Path(d) / "e.db")
            ev.append({"claim": "a", "by": "agent", "trust": "inferred"})
            ev.append({"claim": "b", "by": "agent", "trust": "stated"})
            self.assertEqual(ev.verify(), (True, None))
            with self.assertRaises(ValueError):
                ev.append({"claim": "c", "by": "agent", "trust": "certain"})
            con = sqlite3.connect(ev.path)
            with self.assertRaises(sqlite3.DatabaseError):  # the triggers refuse edits
                con.execute("UPDATE evidence SET raw = 'x' WHERE seq = 1")
            con.execute("DROP TRIGGER evidence_no_update")   # whoever can write the file can drop them
            raw = json.loads(con.execute("SELECT raw FROM evidence WHERE seq = 1").fetchone()[0])
            raw["claim"] = "rewritten"
            con.execute("UPDATE evidence SET raw = ? WHERE seq = 1", (json.dumps(raw),))
            con.commit()
            con.close()
            self.assertEqual(ev.verify(), (False, 1))        # ... and the chain shows it


if __name__ == "__main__":
    unittest.main()
