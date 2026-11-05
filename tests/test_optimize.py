"""The optimizer slot: the catalog, each optimizer through tune, and the selector's policy."""

import unittest

from morphogen import optimize as O
from tests.fixture import ScoredProject

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


class Catalog(unittest.TestCase):
    def test_entries_and_availability(self):
        entries = {e["name"]: e for e in O.catalog()}
        self.assertLessEqual({"grid", "random", "hillclimb", "optuna", "selector", "gepa", "selector-llm"}, set(entries))
        self.assertTrue(all(entries[n]["available"] for n in ("grid", "random", "hillclimb", "selector")))
        self.assertEqual(entries["gepa"]["kind"], "planned")
        self.assertFalse(entries["gepa"]["available"])
        with self.assertRaises(LookupError):
            O.make("gepa")
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


if __name__ == "__main__":
    unittest.main()
