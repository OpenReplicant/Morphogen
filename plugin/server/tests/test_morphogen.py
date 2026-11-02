"""End-to-end tests: conformance of the files backend, and the judge on the sample target."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from morphogen.backend_files import FilesEvidenceLog, FilesListStore
from morphogen import judge as judge_mod
from morphogen import project
from morphogen.config import load_config

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "targets" / "slow-script"

FAST = '''"""Most frequent words in a text."""
from collections import Counter


def normalise(text):
    words = [w.strip(".,;:!?\\"'()[]").lower() for w in text.split()]
    return [w for w in words if w]


def top_words(text, k):
    counts = Counter(normalise(text))
    return sorted(counts.items(), key=lambda p: (-p[1], p[0]))[:k]
'''

WRONG = FAST.replace("(-p[1], p[0])", "(-p[1], len(p[0]))")  # breaks alphabetical tie order

CHEAT_BENCH = 'import json\nprint(json.dumps({"seconds": 0.000001}))\n'


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


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
    """The judge passes a real speed-up and fails a wrong answer and a rigged benchmark."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        os.environ["MORPHOGEN_PRIVATE"] = str(cls.tmp / "private")
        cls.repo = cls.tmp / "proj"
        cls.repo.mkdir()
        git(cls.repo, "init", "-q", "-b", "main")
        git(cls.repo, "config", "user.email", "t@example.com")
        git(cls.repo, "config", "user.name", "test")
        project.init_project(cls.repo)
        project.install_sample(cls.repo, "slow-script", None)
        (cls.repo / "morphogen.yaml").write_text(
            (cls.repo / "morphogen.yaml").read_text().replace("sandbox: auto", "sandbox: none"))
        git(cls.repo, "add", "-A")
        git(cls.repo, "commit", "-q", "-m", "base")
        cls.cfg = load_config(cls.repo)
        _, cls.evidence = project.stores(cls.repo, cls.cfg)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def branch(self, name, files):
        git(self.repo, "checkout", "-q", "-B", name, "main")
        for rel, text in files.items():
            (self.repo / "targets/slow-script" / rel).write_text(text)
        git(self.repo, "commit", "-q", "-am", name)
        git(self.repo, "checkout", "-q", "main")
        return name

    def run_judge(self, candidate):
        return judge_mod.judge(self.repo, self.cfg, "targets/slow-script", "main", candidate, self.evidence)

    def test_faster_and_correct_passes(self):
        r = self.run_judge(self.branch("fast", {"topwords.py": FAST}))
        self.assertEqual(r["verdict"], "pass", r)
        self.assertGreater(r["metrics"]["seconds"]["gain"], 0.5)

    def test_wrong_tie_order_fails(self):
        r = self.run_judge(self.branch("wrong", {"topwords.py": WRONG}))
        self.assertEqual(r["verdict"], "fail", r)

    def test_rigged_benchmark_is_ignored(self):
        r = self.run_judge(self.branch("cheat", {"bench.py": CHEAT_BENCH}))
        self.assertEqual(r["verdict"], "fail", r)  # base's bench.py is used; no real gain

    def test_verdicts_are_measured_evidence_and_chain_holds(self):
        self.run_judge(self.branch("fast2", {"topwords.py": FAST}))
        recs = self.evidence.query(by="judge")
        self.assertTrue(recs and all(r["trust"] == "measured" for r in recs))
        self.assertEqual(self.evidence.verify(), (True, None))

    def test_measure_records_baseline(self):
        r = judge_mod.measure(self.repo, self.cfg, "targets/slow-script", "main", self.evidence)
        self.assertIn("seconds", r["metrics"])

    def test_doctor_reports_guarantees(self):
        d = project.doctor(self.repo)
        self.assertEqual(d["evidence"]["chain"], "intact")
        self.assertIn("judge_outside_project", d["guarantees"])


if __name__ == "__main__":
    unittest.main()
