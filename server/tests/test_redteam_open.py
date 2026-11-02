"""Cheats that currently pass the judge. Each is a judge bug.

Every candidate here keeps the slow, quadratic top_words and still gets a
pass, because timing and correctness are checked in separate runs and the
code can tell them apart, or because the benchmark can be fed a fake input.

The tests are marked expectedFailure so the suite stays green while the bugs
are open. When the judge is fixed, a test reports "unexpected success": remove
its decorator and move it into test_redteam.py.

Suggested fixes: verify outputs inside the timed runs (compare a digest of
each benchmark run's output, base against candidate, per pair); reject added
files or packages whose import name matches a harness module; use a fresh
bench seed per round; give each run its own TMPDIR and HOME without a sandbox.
"""

import unittest

from tests.fixture import SANDBOX, SampleProject

# 1. Behave correctly everywhere except under the benchmark, which never checks
#    output. MORPHOGEN_SEED is set for measured runs only; the check and the
#    equivalence runs do not see it. Survives the Docker runner too (-e).
SNIFF_TAIL = '''
import os as _os
_SLOW = top_words


def top_words(text, k):
    if "MORPHOGEN_SEED" in _os.environ:
        return []
    return _SLOW(text, k)
'''

# 2. Shadow a harness module with a package. Python's path finder prefers a
#    package directory to a module file of the same name, so bench.py imports
#    this instead of the base's gen.py. Equivalence runs `python gen.py` as a
#    script and is unaffected. The overlay copies harness files but leaves
#    extra candidate files in place.
FAKE_GEN = '''def text(seed, n):
    return "a b c"
'''

# 3. Cache results on disk across processes: one judge call uses the same
#    bench seed for every round, so after the first run every run is a hit.
#    Applies to sandbox: none only. Under Docker each run is a fresh container
#    (--rm, read-only tree), so the cache never hits and the judge fails it.
DISK_CACHE_TAIL = '''
import hashlib as _h, json as _j, os as _o, tempfile as _tf
_SLOW = top_words


def top_words(text, k):
    p = _o.path.join(_tf.gettempdir(), "mg_" + _h.sha1((text + str(k)).encode()).hexdigest())
    try:
        with open(p) as f:
            return [tuple(x) for x in _j.load(f)]
    except (OSError, ValueError):
        r = _SLOW(text, k)
        with open(p, "w") as f:
            _j.dump(r, f)
        return r
'''


class OpenCheats(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = SampleProject()
        cls.slow = cls.p.original("topwords.py")

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def assertFails(self, name, files):
        r = self.p.judge(self.p.branch(name, files))
        self.assertEqual(r["verdict"], "fail", f"cheat {name!r} passed the judge: {r}")

    @unittest.expectedFailure
    def test_sniff_the_benchmark_environment(self):
        self.assertFails("env-sniff", {"topwords.py": self.slow + SNIFF_TAIL})

    @unittest.expectedFailure
    def test_shadow_a_harness_module_with_a_package(self):
        self.assertFails("gen-package", {"gen/__init__.py": FAKE_GEN})

    # Open only without a sandbox; under a container runner the judge already catches it.
    @(unittest.expectedFailure if SANDBOX == "none" else (lambda f: f))
    def test_cache_results_on_disk_across_runs(self):
        self.assertFails("disk-cache", {"topwords.py": self.slow + DISK_CACHE_TAIL})


if __name__ == "__main__":
    unittest.main()
