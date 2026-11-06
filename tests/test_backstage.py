"""Backstage's catalog-info.yaml as a source of cells: refs, Location targets, the mapping to cells
and interfaces, merging with morphogen.yaml, and the judge on a project described in both."""

import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from morphogen import backstage as bs
from morphogen import judge as judge_mod
from morphogen.project import Project, ProjectError
from tests.fixture import CLASSIFY, CLASSIFY_BENCH, CLASSIFY_CELL, CONTRACT_TEST, ScoredProject, StructuredProject

HERE = Path(__file__).resolve().parent / "fixtures" / "backstage"
BETTER = CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 50")
BREAKS_NEIGHBOUR = BETTER.replace('def label(x):\n', 'def label(x):\n    if x < 0:\n        raise ValueError("negative")\n')


def entity(kind, name, spec=None, annotations=None):
    md = {"name": name, **({"annotations": annotations} if annotations else {})}
    return {"apiVersion": "backstage.io/v1alpha1", "kind": kind, "metadata": md, "spec": spec or {}}


def catalog(provides=True, consumes=True, change=None):
    """The classifier's system as the catalog sees it: `app` holds `classify`, which provides the
    labels API that `report` consumes; the API's contract test is an annotation."""
    classify = {"type": "service", "lifecycle": "production", "owner": "team-a", "system": "app"}
    if provides:
        classify["providesApis"] = ["labels"]
    report = {"type": "service", "lifecycle": "production", "owner": "team-a", "system": "app"}
    if consumes:
        report["consumesApis"] = ["labels"]
    docs = [entity("System", "app", {"owner": "team-a"}),
            entity("Component", "classify", classify, {"morphogen.dev/change": change} if change else None),
            entity("Component", "report", report),
            entity("API", "labels", {"type": "openapi", "lifecycle": "production", "owner": "team-a",
                                     "definition": "openapi: 3.0.0"},
                   {"morphogen.dev/tests": "python -m unittest -q contracts.test_labels"})]
    return yaml.safe_dump_all(docs, sort_keys=False)


class CatalogProject(ScoredProject):
    """The structured classifier, half in catalog-info.yaml (the system, the components, the API and
    its test) and half in morphogen.yaml (how `classify` is changed and judged)."""

    def __init__(self, cell=None, catalog_text=None):
        cell = cell or copy.deepcopy(CLASSIFY_CELL)
        super().__init__(cells={"component:classify": cell}, settings={"backstage": "catalog-info.yaml"},
                         root_files={"catalog-info.yaml": catalog_text or catalog(),
                                     "contracts/__init__.py": "", "contracts/test_labels.py": CONTRACT_TEST})


class Refs(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(bs.parse_ref("labels", "api"), "api:default/labels")
        self.assertEqual(bs.parse_ref("Component:Ops/Web", "api"), "component:ops/web")
        self.assertEqual(bs.parse_ref("internal/streetlights", "api", "external"), "api:internal/streetlights")
        self.assertEqual(bs.parse_ref("petstore", "api", "external"), "api:external/petstore")
        for bad in ("", ":x", "a:/x", "a:b/"):
            with self.assertRaises(bs.CatalogError, msg=bad):
                bs.parse_ref(bad, "api")


class Examples(unittest.TestCase):
    """Backstage's own example entities (tests/fixtures/backstage, Apache-2.0)."""

    @classmethod
    def setUpClass(cls):
        cls.p = Project.from_dict({"backstage": "catalog-info.yaml"}, root=HERE)
        cls.s = cls.p.structure()

    def test_cells_and_nesting(self):
        self.assertEqual(sorted(self.s.cells), sorted([
            "domain:default/audio", "domain:default/artists", "system:default/artist-engagement-portal",
            "component:default/artist-lookup", "component:default/www-artist", "component:default/wayback-archive",
            "component:default/wayback-archive-ingestion", "component:default/wayback-archive-storage"]))
        self.assertEqual(self.s.parent("domain:default/artists"), "domain:default/audio")          # subdomainOf
        self.assertEqual(self.s.parent("system:default/artist-engagement-portal"), "domain:default/artists")
        self.assertEqual(self.s.parent("component:default/www-artist"), "system:default/artist-engagement-portal")
        self.assertEqual(self.s.parent("component:default/wayback-archive-storage"), "component:default/wayback-archive")

    def test_interfaces(self):
        self.assertEqual(self.s.providers("api:default/wayback-archive"), ["component:default/wayback-archive"])
        self.assertEqual(self.s.interfaces["resource:default/artists-db"].external, "provides")     # dependsOn
        self.assertEqual(self.s.consumers("resource:default/artists-db"), ["component:default/artist-lookup"])
        # a component listed as an API is provided by that component
        self.assertEqual(self.s.providers("component:default/artist-lookup"), ["component:default/artist-lookup"])
        self.assertEqual(self.s.consumers("component:default/artist-lookup"), ["component:default/www-artist"])
        self.assertEqual(self.p.errors(), [])

    def test_every_file_read_is_a_rule_file(self):
        self.assertIn("components/wayback.yaml", self.p.rule_files)    # two documents in one file
        self.assertIn("catalog-info.yaml", self.p.rule_files)
        self.assertEqual(self.p.sources["component:default/wayback-archive"], "backstage (components/wayback.yaml)")
        self.assertFalse(self.p.allows(list(self.s.cells), "components/wayback.yaml"))

    def test_refused_inputs(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            for bad in ("../outside.yaml", "/etc/hosts", "https://example.com/catalog-info.yaml"):
                with self.assertRaises(ProjectError, msg=bad):
                    Project.from_dict({"backstage": bad}, root=d)
            (d / "loc.yaml").write_text(yaml.safe_dump(entity("Location", "l", {"targets": ["../../x.yaml"]})))
            with self.assertRaises(ProjectError):
                Project.from_dict({"backstage": "loc.yaml"}, root=d)
            for annotations in ({"morphogen.dev/nope": "x"}, {"morphogen.dev/run": 3}):
                (d / "c.yaml").write_text(yaml.safe_dump(entity("Component", "c", {}, annotations)))
                with self.assertRaises(ProjectError, msg=str(annotations)):
                    Project.from_dict({"backstage": "c.yaml"}, root=d)
            with self.assertRaises(ProjectError):
                Project.from_dict({"backstage": "c.yaml"})                 # no directory to read from


class Merge(unittest.TestCase):
    def test_both_sources_and_conflicts(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "catalog-info.yaml").write_text(catalog(change="classify.py"))
            p = Project.from_dict({"backstage": "catalog-info.yaml", "cells": {
                "component:classify": {"run": "python bench.py", "consumes": "extra"},
                "helper": {"in": "Component:Classify"}},
                "interfaces": {"extra": {"tests": "true", "external": "provides"}}}, root=d)
            c = p.doc.cells["component:default/classify"]
            self.assertEqual(c.change, ["classify.py"])                                  # from the annotation
            self.assertEqual(c.run, "python bench.py")                                   # from morphogen.yaml
            self.assertEqual(c.provides, ["api:default/labels"])
            self.assertEqual(c.consumes, ["extra"])
            self.assertEqual(p.doc.cells["helper"].in_, "component:default/classify")
            self.assertIn("and morphogen.yaml", p.sources["component:default/classify"])
            self.assertEqual(p.sources["helper"], "morphogen.yaml")
            self.assertEqual(p.errors(), [])
            p = Project.from_dict({"backstage": "catalog-info.yaml", "cells": {
                "component:classify": {"change": "other.py"}}}, root=d)
            self.assertTrue(any("change" in x for x in p.errors()), p.errors())


class Judged(unittest.TestCase):
    """The judge on the classifier described half in the catalog: the same verdicts as the classifier
    described in morphogen.yaml alone."""

    @classmethod
    def setUpClass(cls):
        cls.p, cls.ref = CatalogProject(), StructuredProject()

    @classmethod
    def tearDownClass(cls):
        cls.p.close()
        cls.ref.close()

    def both(self, name, classify):
        a = self.p.judge(self.p.branch(name, {"classify.py": classify}), target="cell:classify")
        b = self.ref.judge(self.ref.branch(name, {"classify.py": classify}))
        return a, b

    def test_same_verdicts_as_the_cell_file_alone(self):
        first = None
        for name, text, word in (("t50", BETTER, None), ("breaks", BREAKS_NEIGHBOUR, "interface"),
                                 ("t500", CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 500"), "range")):
            a, b = self.both(name, text)
            first = first or a
            self.assertEqual(a["verdict"], b["verdict"], (name, a["reasons"], b["reasons"]))
            if word:
                self.assertTrue(any(word in x for x in a["reasons"]), (name, a["reasons"]))
        self.assertEqual(first["verdict"], "pass", first)
        self.assertEqual(first["cell"], "component:default/classify")
        self.assertEqual([x["interface"] for x in first["interfaces"]], ["api:default/labels"])

    def test_names(self):
        proj = judge_mod.structure_of(self.p.repo)
        for name in ("classify", "component:classify", "component:default/classify", "Component:Default/Classify"):
            self.assertEqual(proj.resolve(name), "component:default/classify", name)


class CatalogCheats(unittest.TestCase):
    """The rules read from the catalog are the judge's, like morphogen.yaml."""

    @classmethod
    def setUpClass(cls):
        cls.p = CatalogProject()

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def assertRefused(self, p, name, files, word="outside"):
        r = p.judge(p.branch(name, files, root=True), target="cell:classify")
        self.assertEqual(r["verdict"], "fail", f"cheat {name!r} passed the judge: {r}")
        self.assertTrue(any(word in x for x in r["reasons"]), r["reasons"])
        return r

    def test_drop_the_interface_from_the_catalog(self):
        self.assertRefused(self.p, "drop-api", {"catalog-info.yaml": catalog(provides=False, consumes=False),
                                                "targets/classify/classify.py": BREAKS_NEIGHBOUR})

    def test_widen_change_with_an_annotation(self):
        rigged = CLASSIFY_BENCH.replace("print(label(x))", 'print("high" if x >= 50 else "low")')
        self.assertRefused(self.p, "annotate", {"catalog-info.yaml": catalog(change="targets/**"),
                                                "targets/classify/bench.py": rigged})

    def test_weaken_the_catalog_for_next_time(self):
        # The operator opened everything (change: "**"). The candidate's gain is honest, and this
        # verdict uses the base's catalog anyway; but it also drops the API from the catalog, so once
        # merged, every later judgment would skip the contract. The catalog is the judge's: refused.
        cell = copy.deepcopy(CLASSIFY_CELL)
        cell["change"] = "**"
        q = CatalogProject(cell=cell)
        try:
            r = self.assertRefused(q, "weaken", {"catalog-info.yaml": catalog(provides=False, consumes=False),
                                                 "targets/classify/classify.py": BETTER})
            self.assertTrue(any("catalog-info.yaml" in x for x in r["reasons"]), r["reasons"])
        finally:
            q.close()

    def test_a_conflict_between_the_sources_is_refused(self):
        q = CatalogProject(catalog_text=catalog(change="targets/classify/bench.py"))
        try:
            with self.assertRaises(judge_mod.JudgeError) as e:
                q.judge(q.branch("any", {"classify.py": BETTER}), target="cell:classify")
            self.assertIn("change", str(e.exception))
        finally:
            q.close()


class DemoSplit(unittest.TestCase):
    """demos/entity-resolution: the structure in catalog-info.yaml, what may change in morphogen.yaml,
    and together the same cells, nesting, interfaces and settings as the demo had in one file."""

    def test_the_demo_reads_both(self):
        from morphogen.structure import Structure
        s = Structure.load(Path(__file__).resolve().parents[1] / "demos" / "entity-resolution" / "morphogen.yaml")
        short = (lambda x: x.split("/")[-1] if x else x)
        shape = {short(c): (short(s.parent(c)), sorted(map(short, s.cells[c].provides)),
                            sorted(map(short, s.cells[c].consumes)), sorted(s.cells[c].parameters)) for c in s.cells}
        self.assertEqual(shape, {
            "er": (None, ["resolver"], ["candidates", "pair-score"], []),
            "blocking": ("er", ["candidates"], [], ["BLOCK_LIMIT", "BLOCK_MAX_DF"]),
            "matcher": ("er", ["pair-score"], ["similarity"],
                        ["ALIASES", "MODEL_MISMATCH", "STOPWORDS", "THRESHOLD", "TYPO_RATIO", "WORD_MISMATCH"]),
            "backend": ("er", ["similarity"], [], ["BACKEND"]),
            "clustering": ("er", [], ["pair-score"], []),
            "speed": ("matcher", [], [], [])})
        r = s.interfaces["api:default/resolver"]
        self.assertEqual((r.tests, r.external), (["python -m unittest discover -s tests -t ."], "consumes"))
        self.assertEqual(s.coverage()["tested"], 4)


if __name__ == "__main__":
    unittest.main()
