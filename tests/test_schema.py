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


class SpecSchema(unittest.TestCase):
    """schemas/morphogen-spec.v1.json carries exactly the fields the code accepts under `spec.morphogen`: the cell's,
    the API's, the System's settings and the option's."""

    def schema(self):
        return json.loads((HERE / "schemas/morphogen-spec.v1.json").read_text())

    def fields(self, name):
        return set(self.schema()["$defs"][name]["properties"])

    def test_the_cell_fields_are_those_the_catalog_accepts(self):
        from morphogen.project import CellDoc, CellRules
        held_by_backstage = {"in", "provides", "consumes", "owner", "lifecycle"}
        accepted = {(f.alias or n) for n, f in CellDoc.model_fields.items()} - held_by_backstage
        self.assertEqual(self.fields("Cell"), accepted)
        self.assertEqual(self.fields("Cell"), set(CellRules.model_fields))

    def test_the_api_fields(self):
        from morphogen.project import InterfaceDoc
        self.assertEqual(self.fields("ApiTests"), set(InterfaceDoc.model_fields))

    def test_the_system_settings(self):
        from morphogen.project import SystemRules
        self.assertEqual(self.fields("SystemSettings"), set(SystemRules.model_fields))
        defaults = self.schema()["$defs"]["SystemSettings"]["properties"]["defaults"]
        self.assertEqual(defaults["$ref"], "#/$defs/Cell")

    def test_the_option_fields(self):
        from morphogen.project import OptionRules
        self.assertEqual(self.fields("Option"), set(OptionRules.model_fields))

    def test_the_whole_is_what_spec_morphogen_accepts(self):
        from morphogen.project import MorphogenSpec
        s = self.schema()
        union = set().union(*(self.fields(r["$ref"].rsplit("/", 1)[1]) for r in s["allOf"]))
        self.assertEqual(union, set(MorphogenSpec.model_fields))
        self.assertIs(s["unevaluatedProperties"], False)

    def test_the_settings_the_catalog_reads_are_the_systems(self):
        from morphogen.backstage import SETTINGS
        self.assertEqual(set(SETTINGS), self.fields("SystemSettings"))

    def test_the_defaults_for_the_settings_match(self):
        from morphogen.documents import Config
        props = self.schema()["$defs"]["SystemSettings"]["properties"]
        for name, f in Config.model_fields.items():
            if name in props and "default" in props[name]:
                self.assertEqual(props[name]["default"], f.default, name)
