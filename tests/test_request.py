"""A request (morphogen/request.py, PLAN.md phase 7a): one document in, one verdict out. The cheats a caller or
an agent could try through a request are in RequestCheats; each must be refused."""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import yaml

from morphogen import request as request_mod
from morphogen.documents import DocumentError
from tests.fixture import CLASSIFY
from tests.fixture_cells import CellsProject

HONEST = CLASSIFY + "LIMIT = 100\n# same\n"


class Requests(unittest.TestCase):
    def setUp(self):
        self.p = CellsProject(code=True)
        self.out = Path(tempfile.mkdtemp(prefix="morphogen-request-"))

    def tearDown(self):
        self.p.close()
        shutil.rmtree(self.out, ignore_errors=True)

    def write(self, data, where=None):
        f = (where or self.out) / "request.yaml"
        f.write_text(yaml.safe_dump(data))
        return f

    def change_request(self, **extra):
        return {"morphogen": "request/v1", "kind": "change", "project": str(self.p.repo), "base": "main",
                "candidate": self.p.branch("honest", {"classify/classify.py": HONEST}), **extra}


class RequestRuns(Requests):
    def test_a_change_request_gives_the_verdict_and_records_its_digest(self):
        data = self.change_request()
        r = request_mod.run(self.write(data))
        self.assertEqual(r["verdict"], "pass", r)
        rec = self.p.evidence.dump()[-1]
        self.assertEqual(rec["request"]["digest"], request_mod.digest(data))
        self.assertEqual(rec["request"]["kind"], "change")

    def test_the_requests_local_settings_replace_the_local_file(self):
        data = self.change_request(local={"sandbox": "none", "sandbox_image": "python:3.13-slim"})
        request_mod.run(self.write(data))
        rec = self.p.evidence.dump()[-1]
        self.assertEqual(rec["settings"]["sandbox_image"], "python:3.13-slim")
        self.assertEqual(rec["settings_from"]["sandbox_image"], "request")

    def test_a_judge_request_scores_against_the_held_out_answers_it_names(self):
        data = {"morphogen": "request/v1", "kind": "judge", "project": str(self.p.repo), "target": "cell:classify",
                "candidate": self.p.branch("same", {"classify/classify.py": HONEST}),
                "local": {"cells": {"classify": {"private": str(self.p.private_dir)}}}}
        r = request_mod.run(self.write(data))
        self.assertIn(r["verdict"], ("pass", "fail"))
        self.assertEqual(self.p.evidence.dump()[-1]["request"]["digest"], request_mod.digest(data))


class RequestCheats(Requests):
    def assertRefused(self, path, why):
        with self.assertRaises(DocumentError) as e:
            request_mod.run(path)
        self.assertIn(why, str(e.exception))

    def test_write_the_request_inside_the_repository(self):
        self.assertRefused(self.write(self.change_request(), where=self.p.repo), "inside the repository")

    def test_carry_rules_in_the_request(self):
        doc = yaml.safe_load((self.p.repo / "morphogen.yaml").read_text())
        doc["interfaces"]["labels"] = []
        self.assertRefused(self.write(self.change_request(cells=doc["cells"], interfaces=doc["interfaces"])),
                           "the rules come from the base commit")

    def test_widen_a_cell_from_the_local_settings(self):
        self.assertRefused(self.write(self.change_request(local={"cells": {"classify": {"change": "**"}}})),
                           "not part of a request")

    def test_put_the_held_out_answers_inside_the_repository(self):
        data = {"morphogen": "request/v1", "kind": "judge", "project": str(self.p.repo), "target": "cell:classify",
                "candidate": self.p.branch("same", {"classify/classify.py": HONEST}),
                "local": {"cells": {"classify": {"private": str(self.p.repo / "classify")}}}}
        with self.assertRaises(Exception) as e:
            request_mod.run(self.write(data))
        self.assertIn("outside", str(e.exception))

    def test_the_digest_shows_an_edited_request(self):
        a = self.change_request()
        b = json.loads(json.dumps(a))
        b["labels"] = {"note": "edited afterwards"}
        self.assertNotEqual(request_mod.digest(a), request_mod.digest(b))


if __name__ == "__main__":
    unittest.main()
