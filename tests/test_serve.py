"""What a judged run is given beyond its tree (morphogen/serve.py, PLAN.md 7b): env values from a file outside
the repository, and services started fresh for each run. The cheats are in test_redteam.ServedCheats."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from morphogen import request as request_mod
from morphogen import serve
from morphogen.documents import load_config
from morphogen.schema import Verdict
from tests.fixture import CLASSIFY
from tests.fixture_cells import CellsProject

SECRET = "s3cret-value-0123456789"
CONTAINER = os.environ.get("MORPHOGEN_TEST_SANDBOX", "none") in ("podman", "docker")


class Served(unittest.TestCase):
    def setUp(self):
        self.p = CellsProject(code=True)
        self.outside = Path(tempfile.mkdtemp(prefix="morphogen-env-"))
        self.env = self.outside / "run.env"
        self.env.write_text(f"# the operator's values\nexport TOKEN='{SECRET}'\nPORT=5432\nKV_KEY=kv-only-0123456789\n")

    def tearDown(self):
        self.p.close()
        shutil.rmtree(self.outside, ignore_errors=True)

    def serve(self, **local):
        doc = yaml.safe_load((self.p.repo / "morphogen.local.yaml").read_text())
        doc.update(local)
        (self.p.repo / "morphogen.local.yaml").write_text(yaml.safe_dump(doc))
        self.p.cfg = load_config(self.p.repo)

    def candidate(self, name, code):
        return self.p.branch(name, {"classify/classify.py": CLASSIFY + "LIMIT = 100\n" + code})

    def test_a_run_gets_the_values_it_is_passed(self):
        self.serve(env={"file": str(self.env), "pass": ["TOKEN", "PORT"], "public": ["PORT"]})
        code = (f"import os\nassert os.environ['TOKEN'] == {SECRET!r}, 'no token'\n"
                "assert os.environ['PORT'] == '5432'\nassert 'KV_KEY' not in os.environ\n")
        r = self.p.change(self.candidate("reads", code))
        self.assertEqual(r["verdict"], "pass", r)

    def test_the_verdict_records_names_and_a_digest_never_a_value(self):
        self.serve(env={"file": str(self.env), "pass": ["TOKEN", "PORT"], "public": ["PORT"]})
        self.p.change(self.candidate("same", "# same\n"))
        rec = self.p.evidence.dump()[-1]
        self.assertEqual(rec["served"]["env"]["pass"], ["PORT", "TOKEN"])
        self.assertEqual(rec["served"]["env"]["public"], ["PORT"])
        self.assertEqual(len(rec["served"]["env"]["digest"]), 64)
        self.assertNotIn(SECRET, json.dumps(rec))
        Verdict.model_validate(rec)
        self.p.change(self.candidate("same-2", "# same again\n"))
        self.assertEqual(self.p.evidence.dump()[-1]["served"]["env"]["digest"], rec["served"]["env"]["digest"])
        self.env.write_text(self.env.read_text().replace(SECRET, SECRET + "-new"))
        self.p.change(self.candidate("same-3", "# and again\n"))
        self.assertNotEqual(self.p.evidence.dump()[-1]["served"]["env"]["digest"], rec["served"]["env"]["digest"])

    def test_nothing_served_records_nothing(self):
        self.p.change(self.candidate("plain", "# same\n"))
        self.assertNotIn("served", self.p.evidence.dump()[-1])

    def test_a_request_can_serve_the_same(self):
        out = Path(tempfile.mkdtemp(prefix="morphogen-request-"))
        try:
            f = out / "request.yaml"
            f.write_text(yaml.safe_dump({
                "morphogen": "request/v1", "kind": "change", "project": str(self.p.repo), "base": "main",
                "candidate": self.candidate("via-request", f"import os\nassert os.environ['TOKEN'] == {SECRET!r}\n"),
                "local": {"sandbox": self.p.cfg["sandbox"], "env": {"file": str(self.env), "pass": ["TOKEN"]}}}))
            self.assertEqual(request_mod.run(f)["verdict"], "pass")
            self.assertEqual(self.p.evidence.dump()[-1]["served"]["env"]["pass"], ["TOKEN"])
        finally:
            shutil.rmtree(out, ignore_errors=True)

    def test_an_untracked_file_in_the_checkout_will_do(self):
        (self.p.repo / ".git" / "info" / "exclude").write_text("morphogen.local.yaml\nrun.env\n")
        shutil.copy(self.env, self.p.repo / "run.env")
        self.serve(env={"file": "run.env", "pass": ["TOKEN"]})
        self.assertEqual(self.p.change(self.candidate("untracked", "# same\n"))["verdict"], "pass")

    def test_the_env_file_reads_as_a_shell_would(self):
        self.assertEqual(serve.read_env_file(self.env), {"TOKEN": SECRET, "PORT": "5432", "KV_KEY": "kv-only-0123456789"})

    @unittest.skipUnless(CONTAINER, "services run only in a container (MORPHOGEN_TEST_SANDBOX=podman)")
    def test_a_service_gets_its_values_and_the_run_reaches_it_by_name(self):
        from tests.fixture_served import KV, kv_service
        svc = {**kv_service(), "env": ["KV_KEY"]}
        self.serve(env={"file": str(self.env), "pass": ["TOKEN"]}, services={"kv": svc})
        code = KV + "import os\nassert kv('get kv_key')[:6] == 'kv-onl', 'the service lacks its value'\nassert 'KV_KEY' not in os.environ\n"
        r = self.p.change(self.candidate("svc", code))
        self.assertEqual(r["verdict"], "pass", r)
        rec = self.p.evidence.dump()[-1]
        self.assertEqual(rec["served"]["services"]["kv"]["env"], ["KV_KEY"])
        self.assertTrue(rec["served"]["services"]["kv"]["id"])
        self.assertNotIn("kv-only-0123456789", json.dumps(rec))


if __name__ == "__main__":
    unittest.main()
