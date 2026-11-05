"""The interface test every backend must pass. Owned by the intent: builders and optimizers read it,
never edit it. Run: python -m unittest discover -s tests (from the demo's directory).

The fixture covers what entity resolution has to get right: aliases, typos, abbreviations,
word order, and near-misses (same brand and product line, different model) that must not match.
"""

import unittest

from er import BACKENDS, make

KNOWN = [
    {"id": "b1", "name": "Sony Turntable PS-LX350H", "manufacturer": "Sony"},
    {"id": "b2", "name": "Sony Turntable PS-LX250H", "manufacturer": "Sony"},
    {"id": "b3", "name": "Netgear ProSafe 5-Port Switch FS105", "manufacturer": "Netgear"},
    {"id": "b4", "name": "Netgear ProSafe 8-Port Switch FS108", "manufacturer": "Netgear"},
    {"id": "b5", "name": "Microsoft Office Professional 2007", "manufacturer": "Microsoft"},
    {"id": "b6", "name": "Microsoft Office Home and Student 2007", "manufacturer": "Microsoft"},
    {"id": "b7", "name": "Canon PowerShot SD1000 Digital Camera", "manufacturer": "Canon"},
    {"id": "b8", "name": "Bose Acoustimass 5 Series III Speaker System AM53BK", "manufacturer": "Bose"},
]

# (mention, id it must resolve to)
SAME = [
    ({"id": "a1", "name": "Sony PSLX350H Belt Drive Turntable"}, "b1"),                  # model without hyphen
    ({"id": "a2", "name": "netgear fs105 prosafe 5 port 10/100 switch"}, "b3"),          # case, word order
    ({"id": "a3", "name": "MS Office Professional 2007"}, "b5"),                         # abbreviation
    ({"id": "a4", "name": "Canon Powershot SD-1000 digital camra"}, "b7"),               # typo, hyphen
    ({"id": "a5", "name": "Bose Acoustimass 5 Series III AM53BK"}, "b8"),                # shorter name
]

# (mention, id it must NOT resolve to): same line, different model
DIFFERENT = [
    ({"id": "n1", "name": "Sony Turntable PS-LX250H"}, "b1"),
    ({"id": "n2", "name": "Netgear ProSafe 8-Port Switch FS108"}, "b3"),
    ({"id": "n3", "name": "Microsoft Office Home and Student 2007"}, "b5"),
]

# nothing known should be returned above the threshold for these
UNKNOWN = [
    {"id": "u1", "name": "Garmin Forerunner 305 GPS Watch"},
    {"id": "u2", "name": "Adobe Photoshop Elements 6"},
]


class Interface:
    backend: str

    def setUp(self):
        self.r = make(self.backend)
        for rec in KNOWN:
            self.r.add(dict(rec))

    def best(self, mention):
        found = self.r.resolve(dict(mention))
        return found[0] if found else (None, 0.0)

    def test_resolves_variants_to_the_same_entity(self):
        for mention, want in SAME:
            with self.subTest(mention=mention["name"]):
                got, score = self.best(mention)
                self.assertEqual(got, self.r.entity_of(want), f"score {score:.2f}")

    def test_does_not_merge_different_models(self):
        for mention, wrong in DIFFERENT:
            with self.subTest(mention=mention["name"]):
                got, _ = self.best(mention)
                self.assertNotEqual(got, self.r.entity_of(wrong))

    def test_unknown_things_resolve_to_nothing(self):
        for mention in UNKNOWN:
            with self.subTest(mention=mention["name"]):
                self.assertEqual(self.r.resolve(dict(mention)), [])

    def test_match_is_a_probability_and_symmetric(self):
        a, b = KNOWN[0], SAME[0][0]
        s1, s2 = self.r.match(a, b), self.r.match(b, a)
        self.assertGreaterEqual(s1, 0.0)
        self.assertLessEqual(s1, 1.0)
        self.assertAlmostEqual(s1, s2, places=9)
        self.assertGreater(s1, self.r.match(KNOWN[0], KNOWN[2]))

    def test_resolve_is_ordered_best_first(self):
        found = self.r.resolve({"id": "q", "name": "Netgear ProSafe Switch"})
        scores = [s for _, s in found]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_add_assigns_a_known_entity_or_a_new_one(self):
        e1 = self.r.add({"id": "a9", "name": "Sony PS-LX350H Turntable"})
        self.assertEqual(e1, self.r.entity_of("b1"))
        e2 = self.r.add({"id": "a10", "name": "Garmin Forerunner 305 GPS Watch"})
        self.assertNotIn(e2, {self.r.entity_of(r["id"]) for r in KNOWN})

    def test_merge_and_split(self):
        e = self.r.merge(self.r.entity_of("b5"), self.r.entity_of("b6"))
        self.assertEqual(self.r.entity_of("b5"), e)
        self.assertEqual(self.r.entity_of("b6"), e)
        e2 = self.r.split(e, ["b6"])
        self.assertNotEqual(self.r.entity_of("b6"), self.r.entity_of("b5"))
        self.assertEqual(self.r.entity_of("b6"), e2)


for _name in BACKENDS:
    globals()[f"Test_{_name}"] = type(f"Test_{_name}", (Interface, unittest.TestCase), {"backend": _name})

if __name__ == "__main__":
    unittest.main()
