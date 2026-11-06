"""The optimizer slot: the catalog, each optimizer through tune, and the selector's policy."""

import unittest

from morphogen import optimize as O
from tests.fixture import ScoredProject, TextProject

SPACE = {"x": {"range": [0, 100], "owner": "agent", "_value": 10},
         "mode": {"choices": ["a", "b", "c"], "owner": "agent", "_value": "a"}}


def score(values):
    """A stand-in for probe gains: best at x=50, mode=b; the base (10, a) scores 0."""
    x, m = values.get("x", 10), values.get("mode", "a")
    return (1 - abs(x - 50) / 50) + (0.2 if m == "b" else 0) - (1 - 40 / 50)


def run(opt, n=60):
    history = []
    for _ in range(n):
        v = opt.propose(SPACE, history)
        if v is None:
            break
        t = O.Trial(v, "", score(v), getattr(opt, "proposer", "") or opt.name)
        history.append(t)
        if hasattr(opt, "observe"):
            opt.observe(t)
    return history


class Writing(unittest.TestCase):
    def test_a_float_is_written_without_step_noise(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "s.py").write_text("RATIO = 0.8\n")
            O.write_parameter(Path(d), {"file": "s.py", "name": "RATIO"}, 0.8 - 0.1)
            self.assertEqual((Path(d) / "s.py").read_text(), "RATIO = 0.7\n")


class Catalog(unittest.TestCase):
    def test_entries_and_availability(self):
        entries = {e["name"]: e for e in O.catalog()}
        self.assertLessEqual({"grid", "random", "hillclimb", "anneal", "optuna", "selector", "gepa", "selector-llm"},
                             set(entries))
        self.assertTrue(all(entries[n]["available"] for n in ("grid", "random", "hillclimb", "anneal", "selector")))
        self.assertEqual((entries["gepa"]["kind"], entries["gepa"]["modalities"]), ("adapter", ["text"]))
        self.assertEqual(entries["selector-llm"]["kind"], "planned")
        with self.assertRaises(LookupError):
            O.make("selector-llm")
        with self.assertRaises(LookupError):
            O.make("nope")


class Optimizers(unittest.TestCase):
    def best(self, history):
        return max(history, key=lambda t: t.gain).values

    def test_grid_and_random(self):
        self.assertEqual(self.best(run(O.make("grid", steps=5))), {"mode": "b", "x": 50})
        b = self.best(run(O.make("random", trials=40, seed=3)))
        self.assertLess(abs(b["x"] - 50), 15)

    def test_hillclimb_climbs_from_the_base(self):
        h = run(O.make("hillclimb", trials=60))
        b = self.best(h)
        self.assertEqual(b["mode"], "b")
        self.assertLessEqual(abs(b["x"] - 50), 2)
        first_batch = [t.values for t in h[:4]]
        self.assertIn({"mode": "a", "x": 35}, first_batch)   # a quarter of the range up from 10

    def test_optuna(self):
        if not O.CATALOG["optuna"].available():
            self.skipTest("optuna not installed (uv sync --extra optuna)")
        b = self.best(run(O.make("optuna", trials=40, seed=1)))
        self.assertLess(abs(b["x"] - 50), 15)

    def test_selector_uses_and_credits_its_members(self):
        sel = O.make("selector", trials=40, seed=2, members=["hillclimb", "random", "grid"])
        h = run(sel)
        used = {t.optimizer for t in h}
        self.assertLessEqual(used, {"hillclimb", "random", "grid"})
        self.assertGreaterEqual(len(used), 2)
        self.assertGreater(max(t.gain for t in h), 0.25)


# Two peaks: a low one beside the base (x=10) and a high one far away. A climber from the base stops
# on the low one.
TRAP = {"x": {"range": [0, 100], "owner": "agent", "_kind": "number", "_value": 10}}


def trap(values):
    x = values.get("x", 10)
    return max(0.3 - abs(x - 20) / 40, 1.0 - abs(x - 80) / 15, 0.0) - 0.05   # the base scores 0.0


def run_on(space, fn, opt, n=80):
    history = []
    for _ in range(n):
        v = opt.propose(space, history)
        if v is None:
            break
        t = O.Trial(v, "", fn(v), getattr(opt, "proposer", "") or opt.name)
        history.append(t)
        if hasattr(opt, "observe"):
            opt.observe(t)
    return history


class LocalOptima(unittest.TestCase):
    def test_a_plain_climb_stops_on_the_low_peak(self):
        best = max(run_on(TRAP, trap, O.make("hillclimb", trials=60)), key=lambda t: t.gain)
        self.assertLess(best.gain, 0.5)

    def test_restarts_find_the_high_peak(self):
        best = max(run_on(TRAP, trap, O.make("hillclimb", trials=80, restarts=4, seed=1)), key=lambda t: t.gain)
        self.assertGreater(best.gain, 0.8)

    def test_annealing_finds_the_high_peak(self):
        best = max(run_on(TRAP, trap, O.make("anneal", trials=80, seed=1)), key=lambda t: t.gain)
        self.assertGreater(best.gain, 0.8)

    def test_a_stagnant_selector_turns_to_another_member(self):
        class Stuck:
            name, kinds = "stuck", {"number"}

            def propose(self, space, history):
                return {"x": 12}

        class Other:
            name, kinds = "other", {"number"}

            def propose(self, space, history):
                return {"x": 80}
        sel = O.Selector([Stuck(), Other()], O.Bandit(c=0.0, prior={"stuck": (9, 9)}), max_trials=12, patience=3)
        h = run_on(TRAP, lambda v: 0.0 if v["x"] == 12 else -0.5, sel, n=12)
        self.assertIn("other", [t.optimizer for t in h[4:]])          # turned away after 3 trials without progress


class Policy(unittest.TestCase):
    def test_bandit_tries_each_then_exploits(self):
        b = O.Bandit(c=0.1)
        h = [O.Trial({}, "", 0.5, "good"), O.Trial({}, "", -0.2, "bad")]
        self.assertEqual(b.choose(["good", "bad", "new"], h), "new")
        self.assertEqual(b.choose(["good", "bad"], h), "good")

    def test_failures_count_against_a_member(self):
        b = O.Bandit(c=0.1)
        h = [O.Trial({}, "", None, "refused"), O.Trial({}, "", 0.0, "plain")]
        self.assertEqual(b.choose(["refused", "plain"], h), "plain")

    def test_a_prior_from_earlier_verdicts_gives_a_head_start(self):
        b = O.Bandit(c=0.0, prior={"veteran": (5, 5)})
        h = [O.Trial({}, "", 0.1, "newbie"), O.Trial({}, "", 0.1, "veteran")]
        self.assertEqual(b.choose(["newbie", "veteran"], h), "veteran")


class TuneWithEach(unittest.TestCase):
    """Every available optimizer, through tune, on the scored classifier: the judge passes its best."""

    @classmethod
    def setUpClass(cls):
        cls.p = ScoredProject(search=True)

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def check(self, name, **options):
        r = O.tune(self.p.repo, self.p.cfg, self.p.target, O.make(name, **options), self.p.evidence,
                   rounds=1, max_trials=options.get("trials", 20))
        self.assertEqual(r["verdict"], "pass", r.get("note") or r.get("judge"))
        self.assertIn(r["best"]["values"]["classify.THRESHOLD"], (49, 50, 51))   # inputs are multiples of 3
        return r

    def test_hillclimb(self):
        self.check("hillclimb", trials=20)

    def test_selector_and_its_labels(self):
        prior = O.prior_from_evidence(self.p.evidence, self.p.target)
        r = self.check("selector", trials=20, seed=4, members=["hillclimb", "grid"], prior=prior)
        rec = self.p.evidence.query(by="judge", where={"kind": "verdict"}, limit=1)[0]
        self.assertEqual(rec["labels"]["optimizer"], "selector")
        self.assertIn(rec["labels"].get("member"), ("hillclimb", "grid"))
        self.assertTrue(all(t["optimizer"] in ("hillclimb", "grid") for t in r["trials"]))
        prior = O.prior_from_evidence(self.p.evidence, self.p.target)
        self.assertTrue(any(n >= 1 for _, n in prior.values()))

    def test_optuna(self):
        if not O.CATALOG["optuna"].available():
            self.skipTest("optuna not installed (uv sync --extra optuna)")
        r = O.tune(self.p.repo, self.p.cfg, self.p.target, O.make("optuna", trials=25, seed=1), self.p.evidence,
                   rounds=1, max_trials=25)
        self.assertEqual(r["verdict"], "pass", r.get("note"))


class TextCells(unittest.TestCase):
    """GEPA on a text cell, through tune: the space is the file's text, each candidate is probed, the
    probe's diagnostics are the model's feedback, and the judge passes the best."""

    @classmethod
    def setUpClass(cls):
        if not O.CATALOG["gepa"].available():
            raise unittest.SkipTest("gepa not installed (uv sync --extra gepa)")
        cls.p = TextProject()

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def test_the_space_holds_the_text(self):
        from morphogen import judge as judge_mod  # noqa: F401
        space = O.space_of(self.p.repo, "reply")
        self.assertEqual(space["reply.targets/reply/reply.txt"]["_kind"], "text")
        self.assertEqual(space["reply.targets/reply/reply.txt"]["_value"], "hi there\n")

    def test_numeric_optimizers_have_nothing_to_search(self):
        from morphogen import judge as judge_mod
        with self.assertRaises(judge_mod.JudgeError):
            O.tune(self.p.repo, self.p.cfg, self.p.target, O.make("hillclimb"), self.p.evidence)

    def test_gepa_improves_the_text_and_the_judge_passes_it(self):
        prompts = []

        def lm(prompt):                       # stands in for the model: reads the feedback, answers in a block
            prompts.append(prompt)
            return "A reply with more of the words the scorer wants:\n```\nhello world morphogen\n```"
        r = O.tune(self.p.repo, self.p.cfg, self.p.target, O.make("gepa", trials=4, lm=lm), self.p.evidence,
                   rounds=1, max_trials=4)
        self.assertEqual(r["verdict"], "pass", r.get("note") or r.get("judge"))
        self.assertEqual(r["best"]["values"]["reply.targets/reply/reply.txt"].strip(), "hello world morphogen")
        self.assertTrue(prompts and "coverage" in str(prompts[0]), prompts[:1])   # the probe's metrics reached it
        rec = self.p.evidence.query(by="judge", where={"kind": "verdict"}, limit=1)[0]
        self.assertEqual(rec["labels"]["optimizer"], "gepa")

    def test_a_model_proposing_text_that_breaks_the_tests_scores_low(self):
        def lm(prompt):
            return "```\n" + " ".join(["hello", "world", "morphogen"] * 6) + "\n```"    # too long: the test fails
        r = O.tune(self.p.repo, self.p.cfg, self.p.target, O.make("gepa", trials=3, lm=lm), self.p.evidence,
                   rounds=1, max_trials=3)
        self.assertIsNone(r["verdict"])
        self.assertTrue(all(t["probe_gain"] is None for t in r["trials"] if t["branch"]), r["trials"])

    @unittest.skipUnless(__import__("os").environ.get("MORPHOGEN_LIVE_MODEL"), "set MORPHOGEN_LIVE_MODEL=1 to call "
                         "claude -p --model sonnet (the operator's subscription)")
    def test_live_with_sonnet(self):
        r = O.tune(self.p.repo, self.p.cfg, self.p.target, O.make("gepa", trials=4), self.p.evidence,
                   rounds=1, max_trials=4)
        self.assertEqual(r["verdict"], "pass", r)


class RogueOptimizers(unittest.TestCase):
    """Red team: an optimizer is untrusted input to tune. A proposal outside the space it was given is
    refused before anything is written, and counts as a failed trial."""

    @classmethod
    def setUpClass(cls):
        cls.p = TextProject()

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def run_rogue(self, proposals, kinds=("text",)):
        class Rogue:
            name = "rogue"

            def __init__(self):
                self.kinds, self.left = set(kinds), list(proposals)

            def propose(self, space, history):
                return self.left.pop(0) if self.left else None
        return O.tune(self.p.repo, self.p.cfg, self.p.target, Rogue(), self.p.evidence, rounds=1, max_trials=5)

    def test_a_name_outside_the_space(self):
        r = self.run_rogue([{"../../etc/passwd": "x"}, {"reply.targets/reply/bench.py": "print(1)"}])
        self.assertIsNone(r["verdict"])
        self.assertTrue(all(t["probe_gain"] is None and "outside" in t["refused"] for t in r["trials"]), r["trials"])

    def test_a_value_out_of_bounds(self):
        q = ScoredProject(search=True)
        try:
            class Rogue:
                name, kinds = "rogue", {"number", "choice"}

                def __init__(self):
                    self.left = [{"classify.THRESHOLD": 1e9}, {"classify.THRESHOLD": "fifty"}]

                def propose(self, space, history):
                    return self.left.pop(0) if self.left else None
            r = O.tune(q.repo, q.cfg, q.target, Rogue(), q.evidence, rounds=1, max_trials=5)
            self.assertTrue(all(t["probe_gain"] is None and t["refused"] for t in r["trials"]), r["trials"])
            self.assertIsNone(r["verdict"])
        finally:
            q.close()

    def test_text_that_is_not_text(self):
        r = self.run_rogue([{"reply.targets/reply/reply.txt": {"not": "text"}}])
        self.assertTrue(r["trials"][0]["refused"], r["trials"])


if __name__ == "__main__":
    unittest.main()
