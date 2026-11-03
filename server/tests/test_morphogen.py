"""Conformance of the files backend, and the judge's ordinary behaviour on the sample target."""

import json
import random
import shutil
import tempfile
import unittest
from pathlib import Path

from morphogen import judge as judge_mod
from morphogen import project
from morphogen.backend_files import FilesEvidenceLog, FilesListStore

from tests.fixture import FAST, TARGET, SampleProject, observed_project

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


class Statistics(unittest.TestCase):
    """The judge's comparison on synthetic paired scores (no runs)."""

    @staticmethod
    def episodes(rng, rate, n):
        return [100.0 if rng.random() < rate else 0.0 for _ in range(n)]

    def compare(self, bs, cs, **metric):
        spec = {"score": {"direction": "higher", "primary": True, **metric}}
        return judge_mod._compare(spec, {"score": bs}, {"score": cs})[0]["score"]

    def test_ties_are_left_out_of_the_sign_test(self):
        # 8 wins and 2 ties: with ties counted as losses p = 0.055; without them p = 1/256.
        bs = [1.0] * 10
        cs = [2.0] * 8 + [1.0] * 2
        c = self.compare(bs, cs, min_improvement=0.10)
        self.assertEqual(c["tied"], 2)
        self.assertAlmostEqual(c["sign_test_p"], 1 / 256, places=5)
        self.assertTrue(c["ok"])

    def test_all_tied_never_passes(self):
        c = self.compare([100.0] * 30, [100.0] * 30, gain="absolute", aggregate="mean", min_improvement=0)
        self.assertFalse(c["ok"])

    def test_pass_fail_scores_a_a_rarely_passes(self):
        rng, passes = random.Random(1), 0
        for _ in range(300):
            bs, cs = self.episodes(rng, 0.5, 30), self.episodes(rng, 0.5, 30)
            passes += self.compare(bs, cs, gain="absolute", aggregate="mean", min_improvement=10)["ok"]
        self.assertLessEqual(passes, 3, "identical success rates passed more often than p <= 0.01 allows")

    def test_pass_fail_scores_detect_a_real_improvement(self):
        # Success rate 30% -> 70% over 30 pairs (the default max_repeats) is detected about 3 times
        # in 4 (74 of 100 when measured). Detecting smaller gains needs more episodes.
        rng, passes = random.Random(2), 0
        for _ in range(100):
            bs, cs = self.episodes(rng, 0.3, 30), self.episodes(rng, 0.7, 30)
            passes += self.compare(bs, cs, gain="absolute", aggregate="mean", min_improvement=10)["ok"]
        self.assertGreaterEqual(passes, 65)

    def test_relative_median_cannot_see_pass_fail_gains(self):
        # Why the options exist: a base episode scoring 0 makes the relative gain 0, and with
        # mostly tied pairs the median gain is 0.
        rng = random.Random(3)
        c = self.compare(self.episodes(rng, 0.3, 30), self.episodes(rng, 0.7, 30), min_improvement=0.10)
        self.assertFalse(c["ok"])

    def test_bad_options_are_refused(self):
        with self.assertRaises(judge_mod.JudgeError):
            self.compare([1.0], [2.0], aggregate="max")


class SelfMap(unittest.TestCase):
    """The map init_project seeds: Morphogen, Claude Code and the host. Also the example for other maps."""

    REFS = {"systems": ["slots"], "slots": ["system", "accepts", "filled_by"], "components": ["type", "source", "system"]}

    def test_references_resolve_and_slots_point_back(self):
        lists = {f.stem: [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
                 for f in (project.SAMPLES / "lists").glob("*.jsonl")}
        ids = {e["id"] for rows in lists.values() for e in rows}
        for kind, fields in self.REFS.items():
            for e in lists[kind]:
                for field in fields:
                    refs = e.get(field) or []
                    for r in refs if isinstance(refs, list) else [refs]:
                        self.assertIn(r, ids, f"{kind} {e['id']}: {field} -> {r} does not exist")
        systems = {e["id"]: e for e in lists["systems"]}
        # The core systems must be there; more may be added (the map grows), as long as references resolve.
        self.assertLessEqual({"morphogen", "claude-code", "host"}, set(systems))
        for slot in lists["slots"]:
            self.assertIn(slot["id"], systems[slot["system"]]["slots"], f"{slot['id']} is not listed by its system")
        for system in systems.values():
            self.assertIn(system.get("interface"), ("direct", "simulated"), system["id"])

    def test_init_project_seeds_it(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            project.init_project(tmp)
            lists, _ = project.stores(tmp, project.load_config(tmp))
            self.assertLessEqual({"morphogen", "claude-code", "host"}, {e["id"] for e in lists.query("systems")})
            # Morphogen -> its harness slot -> Claude Code, which runs on the host.
            harness = lists.get("slots", "morphogen/harness")
            self.assertEqual(lists.get("components", harness["filled_by"])["system"], "claude-code")
            host = lists.get("slots", "claude-code/host")
            self.assertEqual(lists.get("components", host["filled_by"])["system"], "host")
        finally:
            shutil.rmtree(tmp)


class Observer(unittest.TestCase):
    def make(self, collected):
        return observed_project(collected)

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


class ContainerGuarantees(unittest.TestCase):
    """What the container runners claim in their capabilities, checked by running commands.

    Skipped for engines that are not installed and answering.
    """

    def check(self, engine):
        from morphogen import runner
        if not runner.available(engine):
            self.skipTest(f"{engine} is not available")
        caps = runner.capabilities({"sandbox": engine})
        tmp = Path(tempfile.mkdtemp())
        try:
            (tmp / "f.txt").write_text("base")
            cfg = {"sandbox": engine}

            def py(code, **kw):
                return runner.run(f"python -c {json.dumps(code)}", tmp, cfg, **kw)

            r = py("print(open('f.txt').read())")
            self.assertEqual((r.rc, r.out.strip()), (0, "base"), r.err)
            r = py("import os; print(os.environ['X'])", env={"X": "y"})
            self.assertEqual(r.out.strip(), "y", r.err)
            r = py("import sys; print(sys.stdin.read())", stdin="in")
            self.assertEqual(r.out.strip(), "in", r.err)
            self.assertTrue(caps["read_only_tree"])
            r = py("open('f.txt', 'w').write('changed')")
            self.assertNotEqual(r.rc, 0)
            self.assertEqual((tmp / "f.txt").read_text(), "base")
            r = py("open('new.txt', 'w').write('x')")
            self.assertNotEqual(r.rc, 0)
            self.assertFalse((tmp / "new.txt").exists())
            self.assertTrue(caps["network_isolated"])
            r = py("import socket; socket.create_connection(('1.1.1.1', 53), 3)")
            self.assertNotEqual(r.rc, 0)
            self.assertTrue(caps["resource_limits"])
            r = py("b = bytearray(2 * 1024 ** 3); print(len(b))")
            self.assertNotEqual(r.rc, 0, "allocated 2 GiB under a 1 GiB limit")
            r = py("import tempfile, os; p = os.path.join(tempfile.gettempdir(), 'mg'); open(p, 'w').write('1')")
            self.assertEqual(r.rc, 0, r.err)
            r = py("import tempfile, os; print(os.path.exists(os.path.join(tempfile.gettempdir(), 'mg')))")
            self.assertEqual(r.out.strip(), "False", "a file written by one run was visible to the next")
        finally:
            shutil.rmtree(tmp)

    def test_docker(self):
        self.check("docker")

    def test_podman(self):
        self.check("podman")


if __name__ == "__main__":
    unittest.main()
