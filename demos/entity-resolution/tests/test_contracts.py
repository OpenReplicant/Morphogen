"""Contract tests for the three interfaces inside the resolver: what each promises its consumer,
whatever the settings are within their bounds. Owned by the intent, like test_interface.py; each is
named in catalog-info.yaml as its API's tests (morphogen.dev/tests), so a change to any cell whose
scope touches the API must pass it. Run from the demo's directory.
"""

import itertools
import unittest

from er import BACKENDS, make, settings
from er.text import tokens
from tests.test_interface import KNOWN, SAME

NAMES = [r for r in KNOWN] + [m for m, _ in SAME] + [{"id": "x", "name": ""}, {"id": "y", "name": "zzz qqq"}]


def loaded(backend):
    r = make(backend)
    for rec in KNOWN:
        r.add(rec)
    return r


class Candidates(unittest.TestCase):
    """api:candidates (Base.candidates, from blocking): known record ids worth scoring, best first."""

    def test_known_ids_sharing_a_token_at_most_the_limit(self):
        for backend in BACKENDS:
            r = loaded(backend)
            for rec in NAMES:
                toks = tokens(rec)
                got = r.candidates(toks)
                self.assertLessEqual(len(got), settings.BLOCK_LIMIT)
                self.assertEqual(len(got), len(set(got)), "no id twice")
                for rid in got:
                    self.assertIn(rid, r.records)
                    self.assertTrue(set(toks) & set(r.toks[rid]), f"{rid} shares no token with {rec}")
                self.assertEqual(got, r.candidates(list(reversed(toks))), "order of tokens must not matter")


class PairScore(unittest.TestCase):
    """api:pair-score (Base.pair, from matcher): a score in [0, 1] for two token lists."""

    def test_bounded_symmetric_and_highest_for_the_same_name(self):
        for backend in BACKENDS:
            r = loaded(backend)
            toks = [tokens(rec) for rec in NAMES]
            for a, b in itertools.product(toks, repeat=2):
                s = r.pair(a, b)
                self.assertGreaterEqual(s, 0.0)
                self.assertLessEqual(s, 1.0)
                self.assertAlmostEqual(s, r.pair(b, a), places=9)
            for a in toks:
                if a:
                    self.assertGreaterEqual(r.pair(a, a) + 1e-9, max(r.pair(a, b) for b in toks))

    def test_nothing_matches_nothing(self):
        for backend in BACKENDS:
            r = loaded(backend)
            self.assertEqual(r.pair([], tokens(KNOWN[0])), 0.0)


class Similarity(unittest.TestCase):
    """api:similarity (a backend's score, used by matcher): in [0, 1], 1 for the same tokens, 0 for none
    shared."""

    def test_each_backend(self):
        for backend in BACKENDS:
            r = loaded(backend)
            for rec in NAMES:
                t = tokens(rec)
                if t:
                    self.assertAlmostEqual(r.score(t, t), 1.0, places=9)
                    self.assertEqual(r.score(t, ["nothingshared"]), 0.0)
            for a, b in itertools.product([tokens(x) for x in NAMES], repeat=2):
                self.assertGreaterEqual(r.score(a, b), 0.0)
                self.assertLessEqual(r.score(a, b), 1.0 + 1e-9)


if __name__ == "__main__":
    unittest.main()
