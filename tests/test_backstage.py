"""The project's catalog (catalog-info.yaml): refs, Location targets, the mapping to cells and interfaces, the
settings and defaults on the System, options and roles, and the judge on a project whose catalog is split across
files. Every catalog file the judge reads is a rule file: the integrity tests are here."""

import copy
import tempfile
import unittest
from pathlib import Path

import yaml

from morphogen import backstage as bs
from morphogen import judge as judge_mod
from morphogen.documents import DocumentError, load_config, rules_config
from morphogen.project import Project, ProjectError
from tests import catalog as catalog_mod
from tests.fixture import CLASSIFY, CLASSIFY_BENCH, CLASSIFY_CELL, CONTRACT_TEST, ScoredProject, StructuredProject, git

HERE = Path(__file__).resolve().parent / "fixtures" / "backstage"
BETTER = CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 50")
BREAKS_NEIGHBOUR = BETTER.replace('def label(x):\n', 'def label(x):\n    if x < 0:\n        raise ValueError("negative")\n')
ROOT = "catalog-info.yaml"


def entity(kind, name, spec=None, morphogen=None, **md):
    spec = dict(spec or {})
    if morphogen is not None:
        spec["morphogen"] = morphogen
    return {"apiVersion": "backstage.io/v1alpha1", "kind": kind, "metadata": {"name": name, **md}, "spec": spec}


def load(files: dict[str, list | dict | str]) -> Project:
    """A project from catalog files written to a temporary directory (entities, or YAML text, per path)."""
    d = Path(tempfile.mkdtemp())
    for rel, docs in files.items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(docs if isinstance(docs, str) else
                             yaml.safe_dump_all(docs if isinstance(docs, list) else [docs], sort_keys=False))
    return Project.load(d)


class Refs(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(bs.parse_ref("labels", "api"), "api:default/labels")
        self.assertEqual(bs.parse_ref("Component:Ops/Web", "api"), "component:ops/web")
        self.assertEqual(bs.parse_ref("internal/streetlights", "api", "external"), "api:internal/streetlights")
        self.assertEqual(bs.parse_ref("petstore", "api", "external"), "api:external/petstore")
        for bad in ("", ":x", "a:/x", "a:b/"):
            with self.assertRaises(bs.CatalogError, msg=bad):
                bs.parse_ref(bad, "api")

    def test_a_cell_is_named_by_its_name(self):
        self.assertEqual(bs.ref_name("Component:Default/Web", "api"), "web")
        self.assertEqual(bs.ref_name("labels", "api"), "labels")
        self.assertEqual(bs.ref_name("ops/web", "component"), "ops/web")
        self.assertEqual(bs.ref_name("resource:default/db", "component"), "resource:db")


class Examples(unittest.TestCase):
    """Backstage's own example entities (tests/fixtures/backstage, Apache-2.0): a root Location naming seven files."""

    @classmethod
    def setUpClass(cls):
        cls.p = Project.load(HERE)
        cls.s = cls.p.structure()

    def test_cells_and_nesting(self):
        self.assertEqual(sorted(self.s.cells), sorted([
            "audio", "artists", "artist-engagement-portal", "artist-lookup", "www-artist", "wayback-archive",
            "wayback-archive-ingestion", "wayback-archive-storage"]))
        self.assertEqual(self.s.parent("artists"), "audio")                                  # subdomainOf
        self.assertEqual(self.s.parent("artist-engagement-portal"), "artists")
        self.assertEqual(self.s.parent("www-artist"), "artist-engagement-portal")
        self.assertEqual(self.s.parent("wayback-archive-storage"), "wayback-archive")        # subcomponentOf

    def test_interfaces(self):
        self.assertEqual(self.s.providers("wayback-archive"), ["wayback-archive"])
        self.assertEqual(self.s.interfaces["resource:artists-db"].external, "provides")      # dependsOn
        self.assertEqual(self.s.consumers("resource:artists-db"), ["artist-lookup"])
        # a component listed as an API is provided by that component
        self.assertEqual(self.s.providers("artist-lookup"), ["artist-lookup"])
        self.assertEqual(self.s.consumers("artist-lookup"), ["www-artist"])
        self.assertEqual(self.p.errors(), [])

    def test_every_file_read_is_a_rule_file(self):
        self.assertIn("components/wayback.yaml", self.p.rule_files)    # two documents in one file
        self.assertIn("catalog-info.yaml", self.p.rule_files)
        self.assertEqual(self.p.sources["wayback-archive-ingestion"], "components/wayback.yaml")
        self.assertEqual(self.p.sources["api:wayback-archive"], "wayback-archive-api.yaml")
        self.assertFalse(self.p.allows(list(self.s.cells), "components/wayback.yaml"))

    def test_refused_inputs(self):
        for bad in ("../outside.yaml", "/etc/hosts", "https://example.com/catalog-info.yaml"):
            with self.assertRaises(ProjectError, msg=bad):
                load({ROOT: entity("Location", "l", {"targets": [bad]})})
        with self.assertRaises(ProjectError):
            load({ROOT: entity("Location", "l", {"targets": ["../../x.yaml"]})})
        with self.assertRaises(ProjectError):
            load({ROOT: entity("Location", "l", {"targets": ["missing.yaml"]})})
        for rules in ({"nope": "x"}, {"run": 3}, "run: x", {"defaults": {"nope": 1}}):
            with self.assertRaises(ProjectError, msg=str(rules)):
                load({ROOT: entity("Component", "c", {}, rules)})
        self.assertIsNone(Project.load(Path(tempfile.mkdtemp())))        # no catalog, no project

    def test_the_old_annotations_are_not_read(self):
        c = entity("Component", "c")
        c["metadata"]["annotations"] = {"morphogen.dev/run": "python x.py"}
        self.assertIsNone(load({ROOT: c}).doc.cells["c"].run)


class Mapping(unittest.TestCase):
    def test_a_sub_grain_cell_is_a_component_nested_with_subcomponent_of(self):
        p = load({ROOT: [entity("System", "app"),
                         entity("Component", "classify", {"system": "app"}, {"run": "python bench.py"}),
                         entity("Component", "threshold", {"subcomponentOf": "classify"},
                                {"run": "python bench.py", "change": "classify.py#THRESHOLD in 0..100"})]})
        self.assertEqual(p.doc.cells["classify"].in_, "app")
        self.assertEqual(p.doc.cells["threshold"].in_, "classify")
        self.assertEqual(p.doc.cells["threshold"].run, "python bench.py")

    def test_an_api_carries_its_tests(self):
        p = load({ROOT: [entity("Component", "a", {"providesApis": ["labels"]}),
                         entity("API", "labels", {"type": "openapi"}, {"tests": ["true", "false"]}),
                         entity("API", "upstream", {"type": "openapi"}, {"tests": "true", "external": "provides"})]})
        self.assertEqual(p.doc.interfaces["labels"].tests, ["true", "false"])
        self.assertEqual(p.doc.interfaces["upstream"].external, "provides")
        with self.assertRaises(ProjectError):      # cell rules do not belong on an API
            load({ROOT: entity("API", "labels", {"type": "openapi"}, {"run": "x"})})

    def test_an_entity_without_a_run_is_structure(self):
        p = load({ROOT: [entity("System", "app"), entity("Component", "a", {"system": "app"}, {"tests": "true"}),
                         entity("Component", "b", {"system": "app"})]})
        self.assertEqual({n for n, c in p.doc.cells.items() if c.run}, set())
        with self.assertRaises(ProjectError):
            p.spec("a")

    def test_options_and_roles_are_never_cells(self):
        """An option for a role (lifecycle: candidate) and the role itself (type: role) are the catalog's, not the judge's:
        even one that carries a run is skipped, and one that names parts does not put them in the structure."""
        p = load({ROOT: [
            entity("System", "app"),
            entity("Component", "matcher", {"system": "app", "providesApis": ["scoring"]},
                   {"run": "python bench.py", "change": "m.py"}),
            entity("Component", "rapidfuzz", {"type": "library", "lifecycle": "candidate", "system": "app",
                                              "providesApis": ["scoring"]},
                   {"run": "python bench.py", "fills": "matcher", "licence": "MIT",
                    "parameters": {"type": "object"}, "docs": {"url": "https://example.org/docs"},
                    "evaluation": {"need": "faster", "result": "2x"}}),
            entity("Component", "fuzzy-matching", {"type": "role", "system": "app"}, {"run": "python bench.py"}),
            entity("API", "scoring", {"type": "openapi"}, {"tests": "true"})]})
        self.assertEqual(sorted(p.doc.cells), ["app", "matcher"])
        self.assertEqual(p.doc.interfaces["scoring"].tests, "true")

    def test_two_cells_may_not_share_a_name(self):
        with self.assertRaises(ProjectError) as e:
            load({ROOT: [entity("System", "x"), entity("Component", "x")]})
        self.assertIn("rename", str(e.exception))
        p = load({ROOT: [entity("Component", "x"), entity("Component", "x", namespace="other")]})
        self.assertEqual(sorted(p.doc.cells), ["other/x", "x"])


class Settings(unittest.TestCase):
    def test_the_system_carries_the_settings(self):
        p = load({ROOT: [entity("System", "app", {}, {"trunk": "trunk", "sandbox": "podman",
                                                      "sandbox_image": "python:3.13-slim",
                                                      "budget": {"trials_per_day": 3},
                                                      "autonomy": {"experimental": "merge"}}),
                         entity("Component", "a", {"system": "app", "lifecycle": "experimental"})]})
        self.assertEqual(p.settings["trunk"], "trunk")
        self.assertEqual(p.settings["budget"], {"trials_per_day": 3})
        self.assertEqual(p.gate("a", True)["decision"], "merge")
        self.assertEqual(p.gate("a", False)["decision"], "none")

    def test_more_than_one_system_with_settings_is_refused(self):
        with self.assertRaises(ProjectError) as e:
            load({ROOT: [entity("System", "one", {}, {"sandbox": "none"}), entity("System", "two", {}, {"trunk": "x"})]})
        self.assertIn("more than one System", str(e.exception))
        p = load({ROOT: [entity("System", "one", {}, {"sandbox": "none"}), entity("System", "two", {}, {"tests": "true"})]})
        self.assertEqual(p.settings, {"sandbox": "none"})        # a System with only cell rules carries no settings

    def test_settings_on_anything_but_a_system_are_refused(self):
        for kind in ("Component", "Domain", "API"):
            with self.assertRaises(ProjectError, msg=kind):
                load({ROOT: entity(kind, "x", {}, {"sandbox": "none"})})

    def test_a_bad_setting_is_refused(self):
        for rules in ({"sandbox": "chroot"}, {"autonomy": {"x": "always"}}, {"budget": 3}):
            with self.assertRaises(ProjectError, msg=str(rules)):
                load({ROOT: entity("System", "app", {}, rules)})

    def test_defaults_are_inherited_unless_the_cell_sets_its_own(self):
        p = load({ROOT: [
            entity("System", "app", {}, {"defaults": {"tests": "python -m unittest -q", "timeout": 60,
                                                      "rounds": {"repeats": 4}}}),
            entity("Component", "a", {"system": "app"}, {"run": "python a.py", "timeout": 5}),
            entity("Component", "inner", {"subcomponentOf": "a"}, {"run": "python i.py"}),
            entity("Component", "bare", {"system": "app"}),
            entity("Component", "elsewhere", {}, {"run": "python e.py"})]})
        a, inner = p.doc.cells["a"], p.doc.cells["inner"]
        self.assertEqual((a.timeout, a.tests, a.rounds.repeats), (5, "python -m unittest -q", 4))
        self.assertEqual((inner.timeout, inner.tests), (60, "python -m unittest -q"))   # through its parent, up to the System
        self.assertIsNone(p.doc.cells["bare"].timeout)                     # no rules of its own: structure
        self.assertIsNone(p.doc.cells["elsewhere"].timeout)                # not in that System
        self.assertIsNone(p.doc.cells["app"].timeout)
        self.assertEqual(p.settings, {})                                     # defaults are not settings

    def test_a_system_with_cell_rules_of_its_own_inherits_too(self):
        p = load({ROOT: [entity("System", "er", {}, {"tests": "true", "defaults": {"run": "python bench.py", "timeout": 9}}),
                         entity("Component", "off", {"system": "er"}, {"change": "x.py", "timeout": None})]})
        self.assertEqual((p.doc.cells["er"].run, p.doc.cells["er"].tests, p.doc.cells["er"].timeout),
                         ("python bench.py", "true", 9))
        self.assertEqual(p.doc.cells["off"].run, "python bench.py")
        self.assertIsNone(p.doc.cells["off"].timeout)          # null opts out of a default

    def test_settings_come_from_the_catalog_for_the_config(self):
        p = StructuredProject()
        try:
            self.assertEqual(p.cfg["sandbox"], p.doc()["sandbox"])
            self.assertEqual(p.cfg["budget"], {"trials_per_day": 0})
        finally:
            p.close()


class SplitProject(StructuredProject):
    """The structured classifier with its catalog split over files, as a project would keep it: the root
    holds a Location and the System (which carries the settings), `catalog/components.yaml` the components,
    `catalog/apis.yaml` the API. `docs/catalog-info.yaml` is a catalog file nothing names."""

    def __init__(self, cell_change=None):
        super().__init__()
        self.cell_change = cell_change
        self.split()

    def split(self, doc=None, loose=True):
        doc = doc or self.doc()
        if self.cell_change:
            doc["cells"]["classify"]["change"] = self.cell_change
        es = catalog_mod.entities(doc)
        root = [e for e in es if e["kind"] == "System"]
        comps = [e for e in es if e["kind"] == "Component"]
        apis = [e for e in es if e["kind"] == "API"]
        loc = entity("Location", "project", {"targets": ["catalog/components.yaml", "catalog/apis.yaml"]})
        git(self.repo, "checkout", "-q", "main")
        self.write_catalog({ROOT: [loc] + root, "catalog/components.yaml": comps, "catalog/apis.yaml": apis})
        if loose:
            self.write_catalog({"docs/catalog-info.yaml": [entity("Component", "notes")]})
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base: a split catalog")
        self.cfg = load_config(self.repo)

    def write_catalog(self, files):
        for rel, docs in files.items():
            self._write(self.repo / rel, yaml.safe_dump_all(docs, sort_keys=False))

    def read_entities(self, rel):
        return list(yaml.safe_load_all((self.repo / rel).read_text()))


class Judged(unittest.TestCase):
    """The judge on the classifier whose catalog is split over files: the same verdicts as the one-file catalog."""

    @classmethod
    def setUpClass(cls):
        cls.p, cls.ref = SplitProject(), StructuredProject()

    @classmethod
    def tearDownClass(cls):
        cls.p.close()
        cls.ref.close()

    def both(self, name, classify):
        a = self.p.judge(self.p.branch(name, {"classify.py": classify}), target="cell:classify")
        b = self.ref.judge(self.ref.branch(name, {"classify.py": classify}))
        return a, b

    def test_same_verdicts_as_the_one_file_catalog(self):
        first = None
        for name, text, word in (("t50", BETTER, None), ("breaks", BREAKS_NEIGHBOUR, "interface"),
                                 ("t500", CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 500"), "range")):
            a, b = self.both(name, text)
            first = first or a
            self.assertEqual(a["verdict"], b["verdict"], (name, a["reasons"], b["reasons"]))
            if word:
                self.assertTrue(any(word in x for x in a["reasons"]), (name, a["reasons"]))
        self.assertEqual(first["verdict"], "pass", first)
        self.assertEqual(first["cell"], "classify")
        self.assertEqual([x["interface"] for x in first["interfaces"]], ["labels"])

    def test_names(self):
        proj = judge_mod.structure_of(self.p.repo)
        for name in ("classify", "component:classify", "component:default/classify", "Component:Default/Classify"):
            self.assertEqual(proj.resolve(name), "classify", name)

    def test_the_rule_files_are_the_catalog_files_the_root_names(self):
        proj = judge_mod.structure_of(self.p.repo)
        self.assertEqual(sorted(proj.rule_files), ["catalog-info.yaml", "catalog/apis.yaml", "catalog/components.yaml"])


class CatalogCheats(unittest.TestCase):
    """Every catalog file the judge reads (the root and each Location target) is a rule file: a candidate that
    changes, adds or removes one is refused, whatever it says, and the rules are the base's."""

    @classmethod
    def setUpClass(cls):
        cls.p = SplitProject()

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def assertRefused(self, name, files, word="outside", p=None, delete=()):
        p = p or self.p
        r = p.judge(p.branch(name, files, root=True, delete=delete), target="cell:classify")
        self.assertEqual(r["verdict"], "fail", f"cheat {name!r} passed the judge: {r}")
        self.assertTrue(any(word in x for x in r["reasons"]), r["reasons"])
        return r

    def edited(self, rel, edit):
        docs = self.p.read_entities(rel)
        edit(docs)
        return yaml.safe_dump_all(docs, sort_keys=False)

    def test_widen_a_cells_rules_in_any_catalog_file(self):
        rigged = CLASSIFY_BENCH.replace("print(label(x))", 'print("high" if x >= 50 else "low")')

        def widen(docs):
            for d in docs:
                if d["metadata"]["name"] == "classify":
                    d["spec"]["morphogen"]["change"] = "targets/**"
        r = self.assertRefused("widen", {"catalog/components.yaml": self.edited("catalog/components.yaml", widen),
                                         "targets/classify/bench.py": rigged})
        self.assertTrue(any("catalog/components.yaml" in x for x in r["reasons"]), r["reasons"])

    def test_edit_the_rules_in_the_root(self):
        def drop(docs):
            for d in docs:
                if d["kind"] == "System":
                    d["spec"]["morphogen"]["budget"] = {"trials_per_day": 1000}
        r = self.assertRefused("root", {ROOT: self.edited(ROOT, drop), "targets/classify/classify.py": BETTER})
        self.assertTrue(any(ROOT in x for x in r["reasons"]), r["reasons"])

    def test_drop_the_interface_from_the_catalog(self):
        def drop(docs):
            for d in docs:
                d["spec"].pop("providesApis", None)
                d["spec"].pop("consumesApis", None)
        self.assertRefused("drop-api", {"catalog/components.yaml": self.edited("catalog/components.yaml", drop),
                                        "targets/classify/classify.py": BREAKS_NEIGHBOUR})

    def test_remove_the_tests_from_an_api(self):
        def drop(docs):
            for d in docs:
                d["spec"].pop("morphogen", None)
        self.assertRefused("untested", {"catalog/apis.yaml": self.edited("catalog/apis.yaml", drop),
                                        "targets/classify/classify.py": BREAKS_NEIGHBOUR}, word="catalog/apis.yaml")

    def test_add_a_location_target(self):
        def add(docs):
            docs[0]["spec"]["targets"].append("catalog/more.yaml")
        r = self.assertRefused("new-target", {ROOT: self.edited(ROOT, add),
                                              "catalog/more.yaml": yaml.safe_dump(entity("Component", "more")),
                                              "targets/classify/classify.py": BETTER})
        self.assertTrue(any(ROOT in x for x in r["reasons"]), r["reasons"])

    def test_add_a_catalog_file_the_root_does_not_name_but_point_at_it(self):
        """The new file only matters if the root names it, and the root is a rule file."""
        r = self.assertRefused("extra-file", {"catalog/extra.yaml": yaml.safe_dump(entity("Component", "x", {}, {"run": "true"})),
                                              "targets/classify/classify.py": BETTER})
        self.assertTrue(any("catalog/extra.yaml" in x for x in r["reasons"]), r["reasons"])

    def test_remove_a_location_target(self):
        r = self.assertRefused("remove-target", {"targets/classify/classify.py": BETTER}, delete=["catalog/apis.yaml"])
        self.assertTrue(any("catalog/apis.yaml" in x for x in r["reasons"]), r["reasons"])

    def test_rename_a_location_target_away(self):
        self.assertRefused("rename-target", {"catalog/apis-moved.yaml": (self.p.repo / "catalog/apis.yaml").read_text(),
                                             "targets/classify/classify.py": BETTER}, delete=["catalog/apis.yaml"])

    def test_the_settings_are_the_bases(self):
        """A candidate's System may say anything; checked out, loaded from the working copy, the judge still uses
        the base's settings and refuses the change to the file."""
        def edit(docs):
            for d in docs:
                if d["kind"] == "System":
                    d["spec"]["morphogen"].update(sandbox="none", sandbox_image="attacker/python:latest",
                                                  budget={"trials_per_day": 1000})
        p = self.p
        cand = p.branch("settings", {ROOT: self.edited(ROOT, edit), "targets/classify/classify.py": BETTER}, root=True)
        base_sha = judge_mod.resolve(p.repo, "main")
        git(p.repo, "checkout", "-q", cand)
        try:
            cfg = load_config(p.repo)
            self.assertEqual(cfg["budget"], {"trials_per_day": 1000})     # the working copy says so
            got = rules_config(p.repo, base_sha, cfg)
            self.assertEqual(got["budget"], {"trials_per_day": 0})
            self.assertEqual(got["sandbox_image"], "python:3.12-slim")
            self.assertEqual(got["settings_from"]["budget"], "base")
            r = judge_mod.judge(p.repo, cfg, "cell:classify", "main", cand, p.evidence)
        finally:
            git(p.repo, "checkout", "-q", "main")
        self.assertEqual(r["verdict"], "fail", r)
        self.assertTrue(any(ROOT in x for x in r["reasons"]), r["reasons"])

    def test_a_file_the_root_does_not_name_is_judged_normally(self):
        """`docs/catalog-info.yaml` is nothing's rules: where a cell may change it, editing it is no cheat."""
        q = SplitProject(cell_change=["targets/classify/classify.py", "targets/classify/classify.py#THRESHOLD in 0..100",
                                      "docs/catalog-info.yaml"])
        try:
            self.assertNotIn("docs/catalog-info.yaml", judge_mod.structure_of(q.repo).rule_files)
            r = q.judge(q.branch("loose", {"docs/catalog-info.yaml": yaml.safe_dump(entity("Component", "notes2", {}, {"run": "x"})),
                                           "targets/classify/classify.py": BETTER}, root=True), target="cell:classify")
            self.assertEqual(r["verdict"], "pass", r)
            self.assertFalse(any("docs/catalog-info.yaml" in x for x in r.get("reasons", [])))
        finally:
            q.close()

    def test_a_file_nothing_may_change_is_still_default_denied(self):
        self.assertRefused("loose-denied", {"docs/catalog-info.yaml": yaml.safe_dump(entity("Component", "notes2")),
                                            "targets/classify/classify.py": BETTER}, word="docs/catalog-info.yaml")

    def test_a_cell_may_not_be_allowed_to_change_the_rules_it_is_judged_by(self):
        """Even when the operator wrote `change: **`, the catalog files stay the judge's."""
        q = SplitProject(cell_change="**")
        try:
            def drop(docs):
                for d in docs:
                    d["spec"].pop("providesApis", None)
                    d["spec"].pop("consumesApis", None)
            docs = q.read_entities("catalog/components.yaml")
            drop(docs)
            r = self.assertRefused("weaken", {"catalog/components.yaml": yaml.safe_dump_all(docs, sort_keys=False),
                                              "targets/classify/classify.py": BETTER}, p=q)
            self.assertTrue(any("catalog/components.yaml" in x for x in r["reasons"]), r["reasons"])
        finally:
            q.close()

    def test_a_broken_catalog_on_the_base_is_refused_by_name(self):
        q = SplitProject()
        try:
            q.write_catalog({"catalog/apis.yaml": [entity("API", "labels", {}, {"run": "x"})]})
            git(q.repo, "commit", "-qam", "base: a bad API")
            with self.assertRaises((judge_mod.JudgeError, DocumentError)) as e:
                q.judge(q.branch("any", {"classify.py": BETTER}), target="cell:classify")
            self.assertIn("catalog/apis.yaml", str(e.exception))
        finally:
            q.close()


class Autonomy(unittest.TestCase):
    """`autonomy` on the System maps a cell's lifecycle to what a pass allows: `merge` (an agent may merge it) or
    `review` (a person decides; the default). The gate is the base's: owner and lifecycle come from the base's
    catalog, the policy from the base's System."""

    def project(self, lifecycle):
        q = StructuredProject()
        doc = q.doc()
        doc["cells"]["classify"]["lifecycle"] = lifecycle
        doc["cells"]["classify"]["owner"] = "team-a"
        doc["autonomy"] = {"experimental": "merge"}
        q.on_main(doc=doc, root=True)
        self.addCleanup(q.close)
        return q

    def test_the_gate_follows_the_lifecycle(self):
        for lifecycle, want in (("experimental", "merge"), ("production", "review")):
            q = self.project(lifecycle)
            r = q.judge(q.branch("better", {"classify.py": BETTER}), target="cell:classify")
            self.assertEqual(r["verdict"], "pass", r)
            self.assertEqual(r["gate"], {"decision": want, "lifecycle": lifecycle, "owner": "group:default/team-a"})
            self.assertEqual(q.evidence.query(limit=1)[0]["gate"], r["gate"])

    def test_no_gate_without_a_pass(self):
        q = self.project("experimental")
        r = q.judge(q.branch("same", {"classify.py": CLASSIFY + "# touched\n"}), target="cell:classify")
        self.assertEqual(r["verdict"], "fail")
        self.assertEqual(r["gate"]["decision"], "none")

    def test_relabel_the_cell_experimental_to_be_merged(self):
        # An honest gain, and the candidate also marks its cell experimental in the catalog so that
        # its pass would be merged without review. The catalog is the judge's: refused.
        q = self.project("production")
        doc = q.doc()
        doc["cells"]["classify"]["lifecycle"] = "experimental"
        r = q.judge(q.branch("relabel", {ROOT: q.dump(doc), "targets/classify/classify.py": BETTER}, root=True),
                    target="cell:classify")
        self.assertEqual(r["verdict"], "fail", r)
        self.assertNotEqual(r["gate"]["decision"], "merge")

    def test_grant_autonomy_in_the_candidates_own_catalog(self):
        q = self.project("production")
        doc = q.doc()
        doc["autonomy"] = {"production": "merge"}
        r = q.judge(q.branch("grant", {ROOT: q.dump(doc), "targets/classify/classify.py": BETTER}, root=True),
                    target="cell:classify")
        self.assertEqual(r["verdict"], "fail", r)
        self.assertNotEqual(r["gate"]["decision"], "merge")


class AiResources(unittest.TestCase):
    """Backstage's AiResource kind (skills and rules, v1.51.0): a skill becomes a cell, nested in its
    system, owned and with a lifecycle, so an agent's skills can be judged as text cells."""

    def test_a_skill_is_a_cell(self):
        docs = [entity("System", "agents", {"owner": "ai-team"}),
                entity("AiResource", "map", {"type": "skill", "lifecycle": "experimental", "owner": "ai-team",
                                             "system": "agents", "dependsOn": ["airesource:default/house-style"]},
                       {"change": "skills/map/SKILL.md"}),
                entity("AiResource", "house-style", {"type": "rule", "lifecycle": "production", "owner": "ai-team",
                                                     "category": "quality", "rationale": "one voice"})]
        cells, ifaces, _, _ = bs.to_cells([{**d, "_file": "catalog-info.yaml"} for d in docs])
        m = cells["map"]
        self.assertEqual((m["in"], m["change"], m["lifecycle"], m["owner"]),
                         ("agents", "skills/map/SKILL.md", "experimental", "group:default/ai-team"))
        self.assertEqual(m["consumes"], ["house-style"])
        self.assertIn("house-style", cells)


class StatusOfARootLocation(unittest.TestCase):
    def test_status_lists_catalog_files_the_root_does_not_name(self):
        from morphogen.status import status
        q = SplitProject()
        try:
            s = status(q.repo, q.cfg)
            self.assertEqual(sorted(s["sources"]["catalog"]["read"]),
                             ["catalog-info.yaml", "catalog/apis.yaml", "catalog/components.yaml"])
            self.assertTrue(any("docs/catalog-info.yaml" in m for m in s["missing"]), s["missing"])
        finally:
            q.close()


class Demos(unittest.TestCase):
    """demos/entity-resolution: one catalog, the structure and what may change, as the demo had in one file."""

    def test_the_demo_reads(self):
        from morphogen.structure import Structure
        s = Structure.load(Path(__file__).resolve().parents[1] / "demos" / "entity-resolution" / ROOT)
        shape = {c: (s.parent(c), sorted(s.cells[c].provides), sorted(s.cells[c].consumes),
                     sorted(s.cells[c].parameters)) for c in s.cells}
        self.assertEqual(shape, {
            "er": (None, ["resolver"], ["candidates", "pair-score"], []),
            "blocking": ("er", ["candidates"], [], ["BLOCK_LIMIT", "BLOCK_MAX_DF"]),
            "matcher": ("er", ["pair-score"], ["similarity"],
                        ["ALIASES", "MODEL_MISMATCH", "STOPWORDS", "THRESHOLD", "TYPO_RATIO", "WORD_MISMATCH"]),
            "backend": ("er", ["similarity"], [], ["BACKEND"]),
            "clustering": ("er", [], ["pair-score"], []),
            "speed": ("matcher", [], [], [])})
        r = s.interfaces["resolver"]
        self.assertEqual((r.tests, r.external), (["python -m unittest discover -s tests -t ."], "consumes"))
        self.assertEqual(s.coverage()["tested"], 4)

    def test_the_f1_workload_is_the_systems_defaults(self):
        p = Project.load(Path(__file__).resolve().parents[1] / "demos" / "entity-resolution")
        for name in ("er", "blocking", "matcher", "backend"):
            c = p.doc.cells[name]
            self.assertEqual((c.run, c.score, c.timeout), ("python bench.py", "python score.py", 300), name)
            self.assertEqual(sorted(p.spec(name)["measure"]["metrics"]), ["scored.f1", "scored.precision"], name)
        self.assertEqual(p.doc.cells["er"].tests, "python -m unittest discover -s tests -t .")
        self.assertIsNone(p.doc.cells["clustering"].run)
        speed = p.spec("speed")                                   # its own measure: wall time, the same output
        self.assertEqual(sorted(speed["measure"]["metrics"]), ["max_rss_kb", "wall_seconds"])
        self.assertTrue(speed["measure"]["same_output"])
        self.assertNotIn("score", speed["measure"])
        self.assertEqual([e["path"] for e in p.changes["matcher"]], ["er/settings.py"] * 4)
        self.assertEqual(p.errors(), [])


if __name__ == "__main__":
    unittest.main()
