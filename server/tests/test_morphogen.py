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


class SimulatedTargets(unittest.TestCase):
    def test_simulated_target_gets_simulated_trust_and_a_note(self):
        from tests.fixture import git
        p = SampleProject()
        try:
            spec = p.path("target.yaml")
            spec.write_text(spec.read_text().replace(
                "interface: direct", "interface: simulated\nsimulates: a word-frequency service in production"))
            git(p.repo, "commit", "-q", "-am", "make it a simulator")
            r = p.judge(p.branch("fast", {"topwords.py": FAST}))
            self.assertEqual(r["verdict"], "pass", r)
            self.assertEqual(r["trust"], "simulated")
            self.assertTrue(any("simulator" in n for n in r["notes"]))
            rec = p.evidence.query(by="judge", limit=1)[0]
            self.assertEqual((rec["trust"], rec["interface"]), ("simulated", "simulated"))
        finally:
            p.close()

    def test_unknown_interface_or_missing_simulates_is_an_error(self):
        from tests.fixture import git
        p = SampleProject()
        try:
            spec = p.path("target.yaml")
            spec.write_text(spec.read_text().replace("interface: direct", "interface: simulated"))
            git(p.repo, "commit", "-q", "-am", "simulated without saying of what")
            with self.assertRaises(judge_mod.JudgeError):
                p.judge(p.branch("x", {"topwords.py": FAST}))
        finally:
            p.close()


OBSERVER = '''import json, os
# Stands in for a query to a telemetry backend: the run's latency, from the
# time window the judge passed in (collected outside the code under test).
start, end = float(os.environ["MORPHOGEN_RUN_START"]), float(os.environ["MORPHOGEN_RUN_END"])
assert os.environ["MORPHOGEN_RUN_ID"] and os.environ["MORPHOGEN_SIDE"] in ("base", "candidate", "measured")
print(json.dumps({"latency_ms": (end - start) * 1000}))
'''


class Observer(unittest.TestCase):
    def make(self, collected):
        from tests.fixture import git
        p = SampleProject()
        (p.path("observe.py")).write_text(OBSERVER)
        spec = p.path("target.yaml")
        text = spec.read_text().replace("harness: [bench.py, gen.py, test_topwords.py]",
                                        "harness: [bench.py, gen.py, test_topwords.py, observe.py]")
        text = text.replace("    wall_seconds: {direction: lower, primary: true, min_improvement: 0.10}",
                            "    wall_seconds: {direction: lower}\n"
                            "    observed.latency_ms: {direction: lower, primary: true, min_improvement: 0.10}")
        text = text.replace("  metrics:\n", f"  observer: {{run: python observe.py, collected: {collected}}}\n  metrics:\n", 1)
        spec.write_text(text)
        git(p.repo, "add", "-A")
        git(p.repo, "commit", "-q", "-m", "observe latency")
        return p

    def test_observed_metric_from_outside_can_decide(self):
        p = self.make("outside")
        try:
            r = p.judge(p.branch("fast", {"topwords.py": FAST}))
            self.assertEqual(r["verdict"], "pass", r)
            self.assertIn("observed.latency_ms", r["metrics"])
            self.assertTrue(r["metrics"]["observed.latency_ms"]["primary"])
        finally:
            p.close()

    def test_self_reported_telemetry_cannot_be_primary(self):
        p = self.make("self")
        try:
            with self.assertRaises(judge_mod.JudgeError):
                p.judge(p.branch("fast", {"topwords.py": FAST}))
        finally:
            p.close()


class Runners(unittest.TestCase):
    def test_runner_settings(self):
        from morphogen import runner
        self.assertEqual(runner.sandbox_mode({"sandbox": "none"}), "none")
        self.assertFalse(runner.capabilities({"sandbox": "none"})["network_isolated"])
        with self.assertRaises(RuntimeError):
            runner.sandbox_mode({"sandbox": "kubernetes"})
        for engine in ("docker", "podman"):
            if not runner.available(engine):
                with self.assertRaises(RuntimeError):
                    runner.sandbox_mode({"sandbox": engine})
        self.assertIn(runner.sandbox_mode({"sandbox": "auto"}), ("docker", "podman", "none"))
