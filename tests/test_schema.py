"""The published schema (schemas/evidence-record.v1.json, from morphogen/schema.py) describes what the judge writes:
the file is current, and every verdict the judge records in the fixtures validates against it."""

import json
import unittest
from pathlib import Path

from morphogen import schema
from tests.fixture import CLASSIFY
from tests.fixture_cells import CellsProject

HERE = Path(__file__).resolve().parents[1]


class Schema(unittest.TestCase):
    def test_the_published_file_is_current(self):
        self.assertEqual(json.loads((HERE / "schemas/evidence-record.v1.json").read_text()), schema.json_schema(),
                         "regenerate: python -m morphogen.schema > schemas/evidence-record.v1.json")

    def test_verdicts_the_judge_writes_validate(self):
        p = CellsProject(code=True)
        try:
            p.change(p.branch("ok", {"classify/classify.py": CLASSIFY + "LIMIT = 100\n# same\n"}))
            p.change(p.branch("bad", {"README.md": "x\n"}))
            p.judge(p.branch("same", {"classify/classify.py": CLASSIFY + "LIMIT = 100\n# again\n"}))
            verdicts = [r for r in p.evidence.dump() if r.get("kind") == "verdict"]
            self.assertEqual(len(verdicts), 3)
            for r in verdicts:
                schema.Verdict.model_validate(r)
        finally:
            p.close()


if __name__ == "__main__":
    unittest.main()
