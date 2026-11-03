"""Conformance of the files backend, and the judge's ordinary behaviour on the sample target."""

import json
import os
import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from morphogen import documents
from morphogen import judge as judge_mod
from morphogen import project
from morphogen import store

from tests.fixture import FAST, TARGET, SampleProject, observed_project, scratch_stores

# Wrong on every input (one word short). A tie-order bug was used before, but it shows only on inputs with
# ties of different lengths, so about one run in a few hundred passed the judge legitimately (#49).
WRONG = FAST.replace(")[:k]", ")[:max(k - 1, 0)]")
assert WRONG != FAST


class ConformanceCases:
    """What every database must do. Mixed into one test class per database."""

    def lists(self, name="lists"):
        raise NotImplementedError

    def evidence(self):
        raise NotImplementedError

    def tamper(self, log):
        """Rewrite the first record behind the backend's back, as an attacker with storage access would."""
        raise NotImplementedError

    def test_lists_put_get_query_follow_dump_load(self):
        s = self.lists()
        s.put("systems", {"id": "sys", "slots": ["sys/a"]})
        s.put("slots", {"id": "sys/a", "accepts": ["type/x"], "filled_by": "comp/c"})
        s.put("types", {"id": "type/x"})
        s.put("components", {"id": "comp/c", "type": "type/x", "tags": ["fast"]})
        self.assertEqual(s.get("types", "type/x"), {"id": "type/x"})
        self.assertEqual([e["id"] for e in s.query("components", {"tags": "fast"})], ["comp/c"])
        self.assertEqual([e["id"] for e in s.query("slots", {"accepts": "~type/"})], ["sys/a"])
        self.assertEqual([e["id"] for e in s.follow("systems", "sys", "slots", 1)], ["sys/a"])
        self.assertEqual([e["id"] for e in s.follow("slots", "sys/a", "filled_by", 1)], ["comp/c"])
        s.put("slots", {"id": "sys/a", "accepts": ["type/x"]})  # a put replaces the entry and its references
        self.assertEqual(s.follow("slots", "sys/a", "filled_by", 1), [])
        dump = s.dump()
        other = self.lists("copy")
        other.load(dump)
        self.assertEqual(other.dump(), dump)
        with self.assertRaises(ValueError):
            s.put("nonsense", {"id": "x"})
        with self.assertRaises(ValueError):
            s.put("types", {"name": "no id"})

    def test_evidence_append_only_and_tamper_evident(self):
        log = self.evidence()
        log.append({"claim": "a", "trust": "measured", "by": "judge", "outcome": {"x": 1e-9, "y": 0.1}})
        log.append({"claim": "b", "trust": "inferred", "by": "agent"})
        self.assertEqual(log.verify(), (True, None))
        self.assertEqual([r["claim"] for r in log.query()], ["b", "a"])
        with self.assertRaises(ValueError):
            log.append({"claim": "c", "trust": "certain", "by": "agent"})
        self.tamper(log)
        self.assertEqual(log.verify(), (False, 1))


class StoreCases(ConformanceCases):
    """Checks on the shared SQL layout, run on each database."""

    def sql(self, db, q, **p):
        from sqlalchemy import text
        with db.engine.connect() as c:
            return [tuple(r) for r in c.execute(text(q), p)]

    def lists(self, name="lists"):
        return store.Lists(self.database(name))

    def evidence(self):
        return store.evidence_log(self.database("ev"))

    def journal(self):
        return store.Log(self.database("jn"), "journal")

    def refused(self, db, q):
        from sqlalchemy import text
        with self.assertRaises(Exception):
            with db.engine.begin() as c:
                c.execute(text(q))

    def test_the_store_fills_the_ports(self):
        from morphogen import ports
        self.assertIsInstance(self.lists(), ports.ListStore)
        for log in (self.evidence(), self.journal()):
            self.assertIsInstance(log, ports.Log)
        s = self.lists()
        s.put("slots", {"id": "sys/a"})
        self.assertEqual(self.sql(s.db, "SELECT id FROM slots"), [("sys/a",)])  # a table per list

    def test_concurrent_writers_get_one_chain(self):
        import threading
        log = self.journal()
        other = store.Log(self.reopen(log.db), "journal")
        errors = []

        def write(lg, tag):
            try:
                for i in range(15):
                    lg.append({"op": "put", "list": "types", "id": f"{tag}{i}", "by": tag})
            except Exception as e:  # pragma: no cover - reported below
                errors.append(e)
        threads = [threading.Thread(target=write, args=(lg, t)) for lg, t in ((log, "a"), (other, "b"))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(log.dump()), 30)
        self.assertEqual(log.verify(), (True, None))


class StoreConformance(StoreCases, unittest.TestCase):
    """On SQLite, the default and the only database tested here."""
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.dbs = []

    def tearDown(self):
        for db in self.dbs:
            db.engine.dispose()
        shutil.rmtree(self.tmp)

    def database(self, name):
        db = store.Database(f"sqlite:///{self.tmp / name}.db")
        self.dbs.append(db)
        return db

    def reopen(self, db):
        again = store.Database(db.url)
        self.dbs.append(again)
        return again

    def tamper(self, log):
        # The triggers refuse the edit, so an attacker with the file would have to drop them first.
        self.refused(log.db, "UPDATE evidence SET raw = 'x' WHERE seq = 1")
        self.refused(log.db, "DELETE FROM evidence")
        from sqlalchemy import text
        with log.db.engine.begin() as c:
            c.execute(text("DROP TRIGGER evidence_no_update"))
            c.execute(text("UPDATE evidence SET raw = replace(raw, '\"claim\":\"a\"', '\"claim\":\"rewritten\"') "
                           "WHERE seq = 1"))

    def test_a_project_from_0_2_files_is_imported_once(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            subprocess.run(["git", "init", "-q", str(tmp)], check=True)
            old = store.Database(f"sqlite:///{tmp / 'scratch.db'}")
            ev = store.evidence_log(old)
            ev.append({"claim": "kept", "trust": "inferred", "by": "agent"})
            (tmp / ".git" / "morphogen").mkdir()
            (tmp / ".git" / "morphogen" / "evidence.jsonl").write_text(
                "".join(store.canonical(r) + "\n" for r in ev.dump()))
            (tmp / ".morphogen" / "lists").mkdir(parents=True)
            (tmp / ".morphogen" / "lists" / "types.jsonl").write_text('{"id": "type/old"}\n')
            (tmp / "morphogen.yaml").write_text("backends: {default: files}\n")  # 0.2's config: ignored now
            cfg = project.load_config(tmp)
            lists, evidence = project.stores(tmp, cfg)
            self.assertEqual([r["claim"] for r in evidence.dump()], ["kept"])
            self.assertEqual(evidence.verify(), (True, None))
            self.assertEqual(lists.get("types", "type/old"), {"id": "type/old"})
        finally:
            shutil.rmtree(tmp)


class Documents(unittest.TestCase):
    """Every document (morphogen.yaml, target.yaml, catalogs.yaml, strategy cards) is read
    through one loader that checks it against its schema and names what is wrong."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def test_the_shipped_documents_load(self):
        root = Path(__file__).resolve().parents[2]
        documents.load("config", root / "samples" / "morphogen.example.yaml")
        documents.load("catalogs", root / "samples" / "catalogs.yaml")
        documents.load("target", root / "samples" / "targets" / "slow-script" / "target.yaml")
        for card in (root / "strategies").glob("*.md"):
            self.assertIn("when", documents.load("strategy", card))

    def test_defaults_are_filled_and_unknown_keys_kept(self):
        (self.tmp / "morphogen.yaml").write_text("trunk: dev\nfuture_key: 1\n")
        cfg = project.load_config(self.tmp)
        self.assertEqual((cfg["trunk"], cfg["data_dir"], cfg["future_key"]), ("dev", ".morphogen", 1))
        self.assertEqual(cfg["database"]["options"], {})

    def test_a_bad_document_names_the_file_and_every_problem(self):
        (self.tmp / "morphogen.yaml").write_text("sandbox: maybe\ndatabase: {options: none}\n")
        with self.assertRaises(documents.DocumentError) as e:
            project.load_config(self.tmp)
        self.assertIn("morphogen.yaml", str(e.exception))
        self.assertEqual(len(e.exception.problems), 2)
        (self.tmp / "card.md").write_text("---\nname: x\n---\nbody")
        with self.assertRaises(documents.DocumentError):
            documents.load("strategy", self.tmp / "card.md")
        (self.tmp / "bad.yaml").write_text("a: [")
        with self.assertRaises(documents.DocumentError):
            documents.load("catalogs", self.tmp / "bad.yaml")

    def test_the_judge_refuses_a_malformed_target(self):
        t = self.tmp / "t"
        t.mkdir()
        (t / "target.yaml").write_text("measure: {run: x, metrics: {wall_seconds: {gain: huge}}}\n")
        with self.assertRaises(judge_mod.JudgeError):
            judge_mod.load_spec(self.tmp, Path("t"))


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

    def test_wrong_output_fails(self):
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
        # The database lives in git's own directory, out of reach of candidate commits.
        self.assertIn("/.git/", str(self.p.evidence.path))

    def test_measure_records_baseline(self):
        r = judge_mod.measure(self.p.repo, self.p.cfg, TARGET, "main", self.p.evidence)
        self.assertIn("wall_seconds", r["metrics"])

    def test_doctor_reports_guarantees(self):
        d = project.doctor(self.p.repo)
        self.assertEqual(d["evidence"]["chain"], "intact")
        self.assertIn("timing", d["guarantees"])


class Probe(unittest.TestCase):
    """Practice runs: feedback for strategies under the judge's rules, never a verdict."""

    @classmethod
    def setUpClass(cls):
        cls.p = SampleProject(trials_per_day=1)
        cls.slow = cls.p.original("topwords.py")

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def probe(self, branch, **kw):
        return judge_mod.probe(self.p.repo, self.p.cfg, TARGET, branch, self.p.evidence, **kw)

    def test_a_right_candidate_gets_clean_cases_and_a_gain_estimate(self):
        r = self.probe(self.p.branch("fast-probe", {"topwords.py": FAST}))
        self.assertFalse(r["binding"])
        self.assertTrue(r["check"]["passed"])
        self.assertTrue(r["cases"] and all(c["status"] == "ok" for c in r["cases"]))
        self.assertGreater(r["metrics"]["wall_seconds"]["gain"], 0.3)
        self.assertEqual(r["timed_output_mismatches"], 0)

    def test_a_wrong_candidate_sees_which_cases_failed_and_how(self):
        r = self.probe(self.p.branch("wrong-probe", {"topwords.py": WRONG}), rounds=0)
        wrong = [c for c in r["cases"] if c["status"] == "wrong"]
        self.assertTrue(wrong)
        self.assertTrue(wrong[0]["expected"] and wrong[0]["got"] and wrong[0]["input"])
        self.assertNotEqual(wrong[0]["expected"], wrong[0]["got"])

    def test_a_difference_past_the_preview_still_shows(self):
        # Seen as a flaky failure: a tie-order difference late in the output was clipped away (#49).
        a = "x" * 1000 + "AB" + "y" * 50
        b = "x" * 1000 + "BA" + "y" * 50
        exp, got = judge_mod._clip_pair(a, b)
        self.assertNotEqual(exp, got)
        self.assertIn("AB", exp)
        self.assertEqual(judge_mod._clip_pair("same", "same"), ("same", "same"))

    def test_forbidden_files_are_refused_before_anything_runs(self):
        r = self.probe(self.p.branch("gen-pkg-probe", {"gen/__init__.py": "def text(seed, n):\n    return 'a'\n"}))
        self.assertTrue(r["forbidden"])
        self.assertNotIn("cases", r)
        self.assertNotIn("metrics", r)

    def test_probes_are_not_verdicts_trials_or_archive_entries(self):
        from morphogen import strategies as S
        self.probe(self.p.branch("fast-probe-2", {"topwords.py": FAST}), cases=1, rounds=1)
        kinds = {r.get("kind") for r in self.p.evidence.dump() if r.get("by") == "judge"}
        self.assertIn("probe", kinds)
        self.assertEqual(S.archive(self.p.evidence, TARGET), [])
        # trials_per_day is 1 here and no judge call has run, so a verdict is still allowed.
        r = self.p.judge(self.p.branch("fast-judged", {"topwords.py": FAST}))
        self.assertIn(r["verdict"], ("pass", "fail"))

    def test_probes_have_their_own_budget(self):
        cfg = {**self.p.cfg, "budget": {"probes_per_day": 1}}
        n = sum(1 for r in self.p.evidence.dump() if r.get("kind") == "probe")
        if n < 1:
            judge_mod.probe(self.p.repo, cfg, TARGET, self.p.branch("one-probe", {"topwords.py": FAST}),
                            self.p.evidence, cases=1, rounds=0)
        with self.assertRaises(judge_mod.JudgeError):
            judge_mod.probe(self.p.repo, cfg, TARGET, "main", self.p.evidence, cases=1, rounds=0)


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
    """The map init_project seeds: Morphogen, its admin UI, Claude Code and the host. Also the example for other maps."""

    REFS = {"systems": ["slots"], "slots": ["system", "accepts", "filled_by"], "components": ["type", "source", "system"],
            "parameters": ["of"]}
    CORE = {"morphogen", "knowledge", "admin-ui", "claude-code", "host"}
    MAP_INTERFACES = ("direct", "simulated", "observed", "none")  # see skills/map/SKILL.md

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
        self.assertLessEqual(self.CORE, set(systems))
        for slot in lists["slots"]:
            self.assertIn(slot["id"], systems[slot["system"]]["slots"], f"{slot['id']} is not listed by its system")
        for system in systems.values():
            self.assertIn(system.get("interface"), self.MAP_INTERFACES, system["id"])
        for kind, rows in lists.items():  # relations resolve too
            for e in rows:
                for rel, v in (e.get("links") or {}).items():
                    for r in v if isinstance(v, list) else [v]:
                        self.assertIn(r, ids, f"{kind} {e['id']}: links.{rel} -> {r} does not exist")

    def test_morphogen_lists_its_parameters_with_owners(self):
        from morphogen.ports import OWNERS
        params = [json.loads(l) for l in (project.SAMPLES / "lists" / "parameters.jsonl").read_text().splitlines() if l]
        self.assertTrue(params)
        for p in params:
            self.assertIn(p.get("owner"), OWNERS, p["id"])
            self.assertTrue(p.get("set_in"), p["id"])
        owners = {p["owner"] for p in params}
        self.assertLessEqual({"judge", "operator", "agent"}, owners)
        self.assertIn("param/judge-significance", {p["id"] for p in params if p["owner"] == "judge"})

    def test_init_project_seeds_it(self):
        tmp = Path(tempfile.mkdtemp())
        try:
            project.init_project(tmp)
            lists, _ = project.stores(tmp, project.load_config(tmp))
            self.assertLessEqual(self.CORE, {e["id"] for e in lists.query("systems")})
            # Morphogen -> its harness slot -> Claude Code, which runs on the host.
            harness = lists.get("slots", "morphogen/harness")
            self.assertEqual(lists.get("components", harness["filled_by"])["system"], "claude-code")
            host = lists.get("slots", "claude-code/host")
            self.assertEqual(lists.get("components", host["filled_by"])["system"], "host")
        finally:
            shutil.rmtree(tmp)


class Structure(unittest.TestCase):
    """Relations (`links`) and parameters are part of a map, checked like its reference fields."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.lists, _ = scratch_stores(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def test_relations_are_walked_and_checked(self):
        s = self.lists
        s.put("slots", {"id": "wm/goal", "system": "wm"})
        s.put("systems", {"id": "wm", "slots": ["wm/goal"]})
        s.put("components", {"id": "comp/planner", "links": {"writes": ["wm/goal"], "next": "comp/actor"}})
        s.put("components", {"id": "comp/actor", "links": {"reads": "wm/goal"}})
        self.assertEqual([e["id"] for e in s.follow("components", "comp/planner", "writes")], ["wm/goal"])
        self.assertEqual([e["id"] for e in s.follow("components", "comp/planner", "next", hops=2)], ["comp/actor"])
        self.assertEqual(s.dangling(), [])
        s.put("components", {"id": "comp/ghost", "links": {"writes": "wm/nothing"}})
        bad = s.dangling()
        self.assertEqual([(d["id"], d["field"], d["why"]) for d in bad], [("comp/ghost", "links.writes", "no such entry")])

    def test_parameters_report_unset_unowned_orphaned_and_tunable(self):
        s = self.lists
        s.put("parameters", {"id": "p/decay", "of": "dm/activation", "default": 0.5, "owner": "agent"})
        s.put("parameters", {"id": "p/beta", "of": "dm/activation", "owner": "agent"})
        s.put("parameters", {"id": "p/alpha", "of": "judge", "value": 0.01, "owner": "nobody"})
        s.put("parameters", {"id": "p/loose", "value": 1, "owner": "operator"})
        r = s.parameter_report()
        self.assertEqual([u["parameter"] for u in r["unset"]], ["p/beta"])
        self.assertEqual([u["parameter"] for u in r["unowned"]], ["p/alpha"])
        self.assertEqual([u["parameter"] for u in r["orphaned"]], ["p/loose"])
        self.assertEqual(sorted(r["tunable"]), ["p/beta", "p/decay"])
        self.assertIn("parameters", s.status())


class Maps(unittest.TestCase):
    """Several maps in one project: mounted read-only, pinned to commits, referenced by qualified ids."""

    HOMELAB = {
        "systems": [{"id": "gpu-box", "interface": "direct", "slots": ["gpu-box/model-server"]}],
        "slots": [{"id": "gpu-box/model-server", "system": "gpu-box", "accepts": ["type/llm-server"],
                   "filled_by": "comp/vllm", "links": {"runs_on": "gpu-box"}}],
        "components": [{"id": "comp/vllm", "type": "type/llm-server", "source": "src/pypi", "system": "gpu-box"},
                       {"id": "comp/gpu-box", "type": "type/machine", "system": "gpu-box"}],
        "types": [{"id": "type/llm-server"}, {"id": "type/machine"}],
        "sources": [{"id": "src/pypi"}],
    }

    def setUp(self):
        from tests.fixture import git
        self.git = git
        self.tmp = Path(tempfile.mkdtemp())
        self.other = self.tmp / "homelab"
        lists = self.other / ".morphogen" / "lists"
        lists.mkdir(parents=True)
        for kind, rows in self.HOMELAB.items():
            (lists / f"{kind}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        git(self.other, "init", "-q", "-b", "main")
        git(self.other, "config", "user.email", "t@example.com")
        git(self.other, "config", "user.name", "test")
        git(self.other, "add", "-A")
        git(self.other, "commit", "-q", "-m", "homelab map")
        self.commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=self.other, capture_output=True,
                                     text=True).stdout.strip()
        self.proj = self.tmp / "proj"
        self.proj.mkdir()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def atlas(self, maps):
        cfg = {"data_dir": ".morphogen", "maps": maps}
        lists, _ = project.stores(self.proj, cfg)
        return lists

    def test_qualified_ids_read_another_map_and_its_references_stay_there(self):
        lists = self.atlas({"homelab": {"path": "../homelab", "commit": self.commit}})
        e = lists.get("slots", "homelab:gpu-box/model-server")
        self.assertEqual(e["_map"], "homelab")
        self.assertEqual(e["_trust"], "stated")
        self.assertEqual(e["filled_by"], "homelab:comp/vllm")  # qualified, so it resolves in homelab
        self.assertEqual(e["links"]["runs_on"], "homelab:gpu-box")  # relations are qualified the same way
        self.assertEqual(lists.get("components", e["filled_by"])["system"], "homelab:gpu-box")
        self.assertIsNone(lists.get("components", "comp/vllm"))  # bare ids mean this project's map

    def test_follow_crosses_from_this_map_into_a_mounted_one(self):
        lists = self.atlas({"homelab": {"path": "../homelab", "commit": self.commit}})
        lists.put("systems", {"id": "assistant", "interface": "direct", "slots": ["assistant/model"]})
        lists.put("slots", {"id": "assistant/model", "system": "assistant", "accepts": ["type/llm"],
                            "filled_by": "homelab:comp/vllm"})
        reached = lists.follow("slots", "assistant/model", "filled_by")
        self.assertEqual([r["id"] for r in reached], ["homelab:comp/vllm"])
        self.assertEqual(lists.follow("components", "homelab:comp/vllm", "system")[0]["id"], "homelab:gpu-box")
        self.assertEqual([e["id"] for e in lists.query("systems", map="homelab")], ["homelab:gpu-box"])
        self.assertEqual({e["id"] for e in lists.query("systems", map="*")}, {"assistant", "homelab:gpu-box"})

    def test_mounted_maps_are_read_only(self):
        lists = self.atlas({"homelab": {"path": "../homelab", "commit": self.commit}})
        with self.assertRaises(PermissionError):
            lists.put("components", {"id": "homelab:comp/vllm", "type": "type/llm-server", "status": "evil"})
        self.assertNotIn("status", lists.get("components", "homelab:comp/vllm"))

    def test_a_pinned_map_ignores_later_commits_and_edits(self):
        lists_dir = self.other / ".morphogen" / "lists"
        (lists_dir / "components.jsonl").write_text(json.dumps({"id": "comp/vllm", "type": "type/x",
                                                                 "status": "changed"}) + "\n")
        self.git(self.other, "commit", "-qam", "later")
        (lists_dir / "systems.jsonl").write_text("")  # and an uncommitted edit
        lists = self.atlas({"homelab": {"path": "../homelab", "commit": self.commit}})
        self.assertNotIn("status", lists.get("components", "homelab:comp/vllm"))
        self.assertIsNotNone(lists.get("systems", "homelab:gpu-box"))
        self.assertTrue(lists.status()["mounted"][0]["pinned"])

    def test_a_git_url_map_is_cloned_and_pinned(self):
        lists = self.atlas({"homelab": {"git": self.other.as_uri(), "commit": self.commit}})
        self.assertIsNotNone(lists.get("systems", "homelab:gpu-box"))
        self.assertIsNone(lists.status()["mounted"][0]["error"])
        lists = self.atlas({"homelab": {"git": self.other.as_uri()}})  # no commit: refused
        self.assertIn("needs a commit", lists.status()["mounted"][0]["error"])

    def test_unpinned_maps_say_so_and_broken_references_are_reported(self):
        lists = self.atlas({"notes": {"path": "../homelab/.morphogen/lists"},
                            "gone": {"path": "../homelab", "commit": "0" * 40}})
        st = lists.status()
        by_name = {m["name"]: m for m in st["mounted"]}
        self.assertFalse(by_name["notes"]["pinned"])
        self.assertIn("not found", by_name["gone"]["error"])
        lists.put("slots", {"id": "a/b", "system": "a", "filled_by": "nowhere:comp/x"})
        lists.put("slots", {"id": "a/c", "system": "a", "filled_by": "notes:comp/missing"})
        refs = {(d["ref"], d["why"]) for d in lists.status()["dangling"]}
        self.assertIn(("nowhere:comp/x", "map 'nowhere' is not mounted"), refs)
        self.assertIn(("notes:comp/missing", "no such entry"), refs)

    def test_report_shows_mounted_maps_and_broken_references(self):
        from morphogen import admin
        cfg = {"data_dir": ".morphogen", "maps": {"homelab": {"path": "../homelab", "commit": self.commit}}}
        lists, evidence = project.stores(self.proj, cfg)
        lists.put("slots", {"id": "a/b", "system": "a", "filled_by": "homelab:comp/nope"})
        html_ = admin.report_html(lists, evidence, "now")
        self.assertIn("Mounted maps", html_)
        self.assertIn("pinned at " + self.commit[:10], html_)
        self.assertIn("homelab:comp/nope", html_)

    def test_catalog_search_finds_entries_in_mounted_maps(self):
        (self.proj / "morphogen.yaml").write_text(
            f"maps:\n  homelab: {{path: ../homelab, commit: {self.commit}}}\n")
        found = project.catalog_search(self.proj, project.load_config(self.proj), "vllm")
        self.assertIn("homelab:comp/vllm", [f.get("id") for f in found])

    def test_a_colon_in_an_id_must_name_a_mounted_map(self):
        lists = self.atlas({})
        with self.assertRaises(ValueError):
            lists.put("slots", {"id": "typo:x", "system": "a"})

    def test_bad_map_names_are_refused(self):
        from morphogen.maps import MapError
        for name in ("Bad Name", "local"):
            with self.assertRaises(MapError):
                self.atlas({name: {"path": "../homelab"}})


class DistributionContract(unittest.TestCase):
    """What docs/distributions.md promises distributions. Adding is fine; removing or renaming breaks them."""

    TOOLS = {
        "doctor": [], "init_project": [], "maps": [], "strategies_list": [], "admin_pages": [],
        "install_sample": ["name", "dest"], "lists_get": ["kind", "id"], "lists_put": ["kind", "entry"],
        "lists_query": ["kind", "where", "follow", "start", "hops", "map"],
        "evidence_query": ["contains", "by", "limit"],
        "evidence_note": ["claim", "source", "trust", "supports", "challenges"],
        "catalog_search": ["query", "limit", "slot"], "measure": ["target", "ref"],
        "lists_export": ["dest"],
        "judge": ["target", "candidate", "base", "labels"], "strategy": ["target"],
        "probe": ["target", "candidate", "base", "cases", "rounds"],
        "archive": ["target", "limit"],
        "journal_append": ["title", "gap", "options", "choice", "rung", "gate", "commit", "why"],
    }

    def test_tools_and_parameters_are_still_there(self):
        import inspect
        from morphogen import mcp_server
        for name, params in self.TOOLS.items():
            fn = getattr(mcp_server, name, None)
            self.assertTrue(callable(fn), f"tool {name} is gone")
            have = list(inspect.signature(inspect.unwrap(fn)).parameters)
            for p in params:
                self.assertIn(p, have, f"tool {name} lost parameter {p}")

    def test_list_kinds_reference_fields_and_interfaces(self):
        from morphogen.maps import REF_FIELDS, SEP
        from morphogen.ports import KINDS, TRUST
        self.assertLessEqual({"systems", "slots", "types", "sources", "components"}, set(KINDS))
        self.assertLessEqual({"slots"}, set(REF_FIELDS["systems"]))
        self.assertLessEqual({"system", "accepts", "filled_by"}, set(REF_FIELDS["slots"]))
        self.assertLessEqual({"type", "source", "system"}, set(REF_FIELDS["components"]))
        self.assertEqual(SEP, ":")
        self.assertLessEqual({"measured", "simulated", "stated", "inferred"}, set(TRUST))
        self.assertLessEqual({"direct", "simulated"}, set(judge_mod.INTERFACES))
        self.assertLessEqual({"wall_seconds", "cpu_seconds", "max_rss_kb"}, set(judge_mod.JUDGE_METRICS))


class Capabilities(unittest.TestCase):
    """Slots say what they require (and why), components what they provide."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        project.init_project(self.tmp)
        self.cfg = project.load_config(self.tmp)
        self.lists, _ = project.stores(self.tmp, self.cfg)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def ids(self, slot):
        return [c["id"] for c in project.candidates(self.tmp, self.cfg, slot)["candidates"]]

    def test_the_smallest_sufficient_filler_comes_first(self):
        self.lists.put("components", {"id": "comp/flat", "type": "type/list-store", "provides": ["exact"]})
        self.lists.put("components", {"id": "comp/graphy", "type": "type/list-store",
                                      "provides": ["exact", "graph", "semantic"]})
        self.lists.put("slots", {"id": "t/store", "system": "t", "accepts": ["type/list-store"], "requires": ["exact"]})
        # Exact lookups only: the flat store covers it with the least overhead.
        r = project.candidates(self.tmp, self.cfg, "t/store")
        self.assertEqual(r["candidates"][0]["id"], "comp/flat")
        self.assertEqual(r["candidates"][0]["missing"], [])
        self.assertIn("graph", [c for c in r["candidates"] if c["id"] == "comp/graphy"][0]["extra"])
        # Require graph traversal too, and the graph store moves ahead; the flat one now misses it.
        self.lists.put("slots", {"id": "t/store", "system": "t", "accepts": ["type/list-store"],
                                 "requires": ["exact", "graph"]})
        r = project.candidates(self.tmp, self.cfg, "t/store")
        self.assertEqual(r["candidates"][0]["id"], "comp/graphy")
        self.assertEqual([c for c in r["candidates"] if c["id"] == "comp/flat"][0]["missing"], ["graph"])

    def test_only_accepted_types_are_candidates_and_catalog_entries_count(self):
        self.assertNotIn("comp/sql-logs", self.ids("knowledge/lists"))
        (self.tmp / "catalogs.yaml").write_text(
            "stores:\n  - name: some-graph-db\n    type: type/list-store\n    provides: [exact, graph, temporal]\n")
        r = project.candidates(self.tmp, self.cfg, "knowledge/lists")
        cat = [c for c in r["candidates"] if c["id"] == "some-graph-db"][0]
        self.assertEqual(cat["from"], "catalogs.yaml/stores")
        self.assertEqual(cat["extra"], ["graph", "temporal"])

    def test_capability_flags_count_as_provided(self):
        self.lists.put("components", {"id": "comp/flagged", "type": "type/log",
                                      "capabilities": {"tamper-evident": True, "concurrent-writers": False}})
        r = project.candidates(self.tmp, self.cfg, "knowledge/logs")
        flagged = [c for c in r["candidates"] if c["id"] == "comp/flagged"][0]
        self.assertEqual((flagged["covers"], flagged["missing"]), (["tamper-evident"], ["concurrent-writers"]))

    def test_the_report_finds_gaps_overhead_and_unexplained_requirements(self):
        report = self.lists.capability_report()
        self.assertEqual(report["gaps"], [])  # the seeded map meets its own requirements
        self.assertEqual(report["unexplained"], [])  # and says why it has each one
        self.assertIn("knowledge/logs", [o["slot"] for o in report["overhead"]])  # SQLite also enforces append-only
        slot = self.lists.get("slots", "knowledge/indices")
        self.lists.put("slots", {**slot, "requires": ["exact", "lexical", "semantic"]})
        report = self.lists.capability_report()
        gap = [g for g in report["gaps"] if g["slot"] == "knowledge/indices"][0]
        self.assertEqual((gap["missing"], gap["why"]), (["semantic"], "filler lacks it"))
        self.assertIn("semantic", [r for u in report["unexplained"] for r in u["requirements"]])
        self.assertEqual(project.doctor(self.tmp)["maps"]["capability_gaps"][0]["slot"], "knowledge/indices")

    def test_the_journal_is_a_log(self):
        r = project.journal_append(self.tmp, self.cfg, {"title": "swap the list store", "gap": "graph walks",
                                                       "choice": "a graph store", "rung": "reuse"})
        self.assertEqual(r["journal_seq"], 1)
        self.assertEqual(project.journal(self.tmp, self.cfg)[0]["choice"], "a graph store")
        self.assertEqual(project.doctor(self.tmp)["journal"]["chain"], "intact")

    def test_unknown_slot_is_an_error(self):
        with self.assertRaises(ValueError):
            project.candidates(self.tmp, self.cfg, "no/such-slot")


class AdminPages(unittest.TestCase):
    """The menu and the report: static, read-only, and safe against what the agent writes."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        project.init_project(self.tmp)
        self.cfg = project.load_config(self.tmp)
        self.lists, self.evidence = project.stores(self.tmp, self.cfg)

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def pages(self):
        from morphogen import admin
        paths = admin.write(self.tmp, self.cfg)
        return Path(paths["menu"]).read_text(), Path(paths["report"]).read_text()

    def test_menu_lists_slots_and_links_installed_tools_in_new_tabs(self):
        menu, _ = self.pages()
        self.assertIn('href="report.html" target="_blank" rel="noopener noreferrer"', menu)
        self.assertIn("<code>sessions</code>", menu)
        self.assertIn("empty", menu)
        self.assertIn("ttyd", menu)  # from the catalog, listed as available
        self.assertIn(".morphogen/admin/", (self.tmp / ".gitignore").read_text())

    def test_an_installed_side_car_appears_as_a_link(self):
        self.lists.put("components", {"id": "comp/ttyd", "name": "ttyd", "type": "type/web-terminal",
                                      "status": "in use", "url": "http://127.0.0.1:7681"})
        slot = self.lists.get("slots", "admin-ui/terminal")
        self.lists.put("slots", {**slot, "filled_by": "comp/ttyd"})
        menu, _ = self.pages()
        self.assertIn('href="http://127.0.0.1:7681"', menu)

    def test_entries_written_by_the_agent_cannot_inject_markup_or_script_links(self):
        self.lists.put("components", {"id": "comp/evil", "name": "<script>alert(1)</script>",
                                      "status": "in use", "url": "javascript:alert(1)"})
        slot = self.lists.get("slots", "admin-ui/editor")
        self.lists.put("slots", {**slot, "filled_by": "comp/evil", "interface": "<img src=x onerror=alert(1)>"})
        self.evidence.append({"claim": "<script>steal()</script>", "trust": "inferred", "by": "agent"})
        menu, report = self.pages()
        for page in (menu, report):
            self.assertNotIn("<script>", page)
            self.assertNotIn("<img", page)
            self.assertNotIn("javascript:", page)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", menu)

    def test_report_shows_the_chain_and_the_lineage(self):
        for seq, (base, cand, verdict) in enumerate([("a" * 40, "b" * 40, "fail"), ("a" * 40, "c" * 40, "pass"),
                                                     ("c" * 40, "d" * 40, "pass")]):
            self.evidence.append({"claim": f"verdict {seq}", "kind": "verdict", "verdict": verdict, "by": "judge",
                                  "trust": "measured", "subject": {"system": "t", "path": "targets/t"},
                                  "refs": {"base": base, "candidate": cand},
                                  "outcome": {"metrics": {"wall_seconds": {"primary": True, "gain": 0.2}}},
                                  "labels": {"strategy": "hill-climb"}})
        _, report = self.pages()
        self.assertIn('chain <span class="pass">intact</span>', report)
        self.assertIn("<code>targets/t</code>", report)
        # d was built on c, which was built on a: nested two levels deep.
        self.assertRegex(report, r"cccccccccc.*<ul class=\"tree\"><li>.*dddddddddd")
        self.assertIn("admin-ui", report)

    def test_serve_is_read_only_and_local(self):
        import threading
        import urllib.error
        import urllib.request
        from morphogen import admin
        out = Path(admin.write(self.tmp, self.cfg)["menu"]).parent
        httpd = admin.make_server(out, 0)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            self.assertEqual(httpd.server_address[0], "127.0.0.1")
            url = f"http://127.0.0.1:{httpd.server_address[1]}/"
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            self.assertEqual(opener.open(url + "index.html").status, 200)
            with self.assertRaises(urllib.error.HTTPError) as e:
                opener.open(urllib.request.Request(url + "index.html", data=b"x", method="POST"))
            self.assertEqual(e.exception.code, 501)
        finally:
            httpd.shutdown()
            httpd.server_close()


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


class SessionHook(unittest.TestCase):
    """The session hook reads the database read-only, with the standard library alone."""

    def test_the_briefing_reads_evidence_and_the_journal(self):
        sp = SampleProject()
        try:
            sp.evidence.append({"claim": "noted", "trust": "inferred", "by": "agent"})
            project.journal_append(sp.repo, sp.cfg, {"title": "tried a hash map", "gap": "g", "options": "o",
                                                     "choice": "c", "rung": "r"})
            hook = Path(__file__).resolve().parents[2] / "hooks" / "morphogen_hook.py"
            r = subprocess.run(["python3", "-I", str(hook), "session"], input="{}", capture_output=True, text=True,
                               env={**os.environ, "CLAUDE_PROJECT_DIR": str(sp.repo)})
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIn("1 records, chain intact", r.stdout)
            self.assertIn("Last journal entry: tried a hash map.", r.stdout)
        finally:
            sp.close()
