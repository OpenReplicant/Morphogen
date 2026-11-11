"""Model calls counted outside the candidate (PLAN.md 7c, morphogen/serve.py): a cell's `better` can name
`metered.*`, what the operator's meter counts at the gateway for each run. The cheats are in
test_redteam.MeteredCheats."""

import os
import unittest

import yaml

from morphogen.documents import load_config
from morphogen.schema import Verdict
from tests.fixture import CLASSIFY, git
from tests.fixture_cells import CellsProject, cells_doc

CONTAINER = os.environ.get("MORPHOGEN_TEST_SANDBOX", "none") in ("podman", "docker")


@unittest.skipUnless(CONTAINER, "a gateway is reached only from a container (MORPHOGEN_TEST_SANDBOX=podman)")
class Metered(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from tests.fixture_gateway import FakeGateway
        cls.gw = FakeGateway()

    @classmethod
    def tearDownClass(cls):
        cls.gw.close()

    def setUp(self):
        from tests.fixture_gateway import CALL
        self.call = CALL
        self.p = CellsProject(code=True)
        doc = yaml.safe_load((self.p.repo / "morphogen.local.yaml").read_text())
        doc.update(self.gw.local())
        (self.p.repo / "morphogen.local.yaml").write_text(yaml.safe_dump(doc))
        doc = cells_doc(code=True)
        doc["cells"]["classify"]["better"] = "metered.calls lower, metered.tokens lower"
        self.p.write("morphogen.yaml", yaml.safe_dump(doc, sort_keys=False))
        self.p.write("classify/classify.py", self.calls(3))
        git(self.p.repo, "commit", "-qam", "base: three calls a run")
        self.p.cfg = load_config(self.p.repo)

    def tearDown(self):
        self.p.close()

    def calls(self, n):
        return CLASSIFY + "LIMIT = 100\n" + self.call + f"for _ in range({n}):\n    call()\n"

    def test_fewer_calls_pass_on_the_gateways_count(self):
        r = self.p.judge(self.p.branch("fewer", {"classify/classify.py": self.calls(1)}))
        self.assertEqual(r["verdict"], "pass", r.get("reasons"))
        rec = self.p.evidence.dump()[-1]
        cmp = rec["outcome"]["metrics"]["metered.calls"]
        self.assertEqual((cmp["base"], cmp["candidate"]), (3, 1), cmp)
        self.assertEqual(rec["served"]["gateway"]["container"], self.gw.container)
        Verdict.model_validate(rec)

    def test_the_same_calls_do_not(self):
        r = self.p.judge(self.p.branch("same", {"classify/classify.py": self.calls(3) + "# same\n"}))
        self.assertEqual(r["verdict"], "fail", r.get("reasons"))


if __name__ == "__main__":
    unittest.main()
