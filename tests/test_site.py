"""The research site (site/, Astro): real input renders with its cross-references, issue links are well formed, text
from papers is escaped, an invalid claim stops the build, and a claim tried on two configurations shows both.

Each test runs the real build (`npm run build` in site/) on a project of its own and checks the files it writes. It
needs Node and `npm ci` in site/; without them it is skipped, unless MORPHOGEN_SITE_TESTS=1 (as in
.github/workflows/site.yml), when a missing toolchain is a failure."""

import copy
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urljoin, urlsplit

import yaml

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
REQUIRED = os.environ.get("MORPHOGEN_SITE_TESTS") == "1"
READY = shutil.which("npm") is not None and (SITE / "node_modules" / "astro").is_dir()

HOSTILE = '<script>alert("x")</script><img src=x onerror=alert(1)>'

CLAIM = {
    "apiVersion": "morphogen.dev/v1alpha1",
    "kind": "EvidenceClaim",
    "metadata": {"name": "hostile-claim", "description": "Method X wins " + HOSTILE},
    "spec": {
        "about": "component:default/opt-x",
        "role": "component:default/role-x",
        "source": {
            "kind": "preprint", "title": "A paper " + HOSTILE, "id": "arXiv:2611.00001",
            "url": "javascript:alert(1)", "version": "v1", "location": "Table 1 " + HOSTILE,
            "read": "in full", "quote": 'It "wins" & <b>beats</b> ' + HOSTILE, "quote_status": "unchecked",
        },
        "claim": {"statement": "X beats Y " + HOSTILE, "finding": "better", "reporting": "self",
                  "metric": "accuracy " + HOSTILE, "value": 0.9, "baseline": {"name": "Y", "value": 0.8}},
        "conditions": {"models": [{"name": "M " + HOSTILE}], "unstated": ["hardware " + HOSTILE]},
        "assessments": [{
            "system": "system:default/sys", "status": "predicted", "date": "2026-11-27",
            "prediction": {"p_transfer": 0.4, "reason": "Different model " + HOSTILE, "by": "test " + HOSTILE,
                           "date": "2026-11-27", "before_outcome": True},
            "trial": {"plan": "Run it " + HOSTILE, "cost_hours": 2.5, "needs": ["data " + HOSTILE]},
        }],
    },
}

CATALOG = [
    {"apiVersion": "backstage.io/v1alpha1", "kind": "System", "metadata": {"name": "sys", "description": "S " + HOSTILE},
     "spec": {"owner": "group:default/g"}},
    {"apiVersion": "backstage.io/v1alpha1", "kind": "Component",
     "metadata": {"name": "role-x", "description": "The role " + HOSTILE},
     "spec": {"type": "role", "lifecycle": "experimental", "owner": "group:default/g"}},
    {"apiVersion": "backstage.io/v1alpha1", "kind": "Component",
     "metadata": {"name": "opt-x", "description": "Option " + HOSTILE},
     "spec": {"type": "method", "lifecycle": "candidate", "owner": "group:default/g",
              "morphogen": {"fills": "component:default/role-x", "evaluation": {"result": "R " + HOSTILE}}}},
    {"apiVersion": "backstage.io/v1alpha1", "kind": "Resource",
     "metadata": {"name": "small-model", "description": "Small Model 1B, Q6_K, on the GPU"}, "spec": {"type": "model"}},
    {"apiVersion": "backstage.io/v1alpha1", "kind": "Resource",
     "metadata": {"name": "big-model", "description": "Big Model 26B, Q4_K"}, "spec": {"type": "model"}},
]


def two_setups() -> dict:
    """A claim tried on two configurations of one system, with different results (#111)."""
    claim = copy.deepcopy(CLAIM)
    claim["metadata"]["name"] = "two-setups"
    claim["spec"]["source"]["url"] = "https://arxiv.org/abs/2611.00001"
    outcome = {"trial": {"id": "T-1"}, "observed": ["hostile-claim"], "comparison": "our-setup",
               "verdict": {"by": "falsifier", "decision": "met"}}
    pred = {"by": "test", "date": "2026-11-27", "before_outcome": True, "reason": "r"}
    claim["spec"]["assessments"] = [
        {"system": "system:default/sys", "against": ["resource:default/small-model"], "status": "did-not-transfer",
         "date": "2026-11-25", "prediction": {**pred, "p_transfer": 0.3},
         "outcome": {**outcome, "summary": "Small model: far below."}},
        {"system": "system:default/sys", "against": ["resource:default/big-model"], "status": "replicated",
         "date": "2026-11-27", "prediction": {**pred, "p_transfer": 0.7},
         "outcome": {**outcome, "summary": "Big model: matched."}},
    ]
    return claim


def scored() -> dict:
    claim = copy.deepcopy(CLAIM)
    claim["metadata"]["name"] = "scored-claim"
    claim["spec"]["source"]["url"] = "https://arxiv.org/abs/2611.00001"
    a = claim["spec"]["assessments"][0]
    a["status"] = "did-not-transfer"
    a["outcome"] = {"trial": {"id": "T-2"}, "observed": ["hostile-claim"], "summary": "Lower.",
                    "comparison": "our-setup", "verdict": {"by": "morphogen", "decision": "refuse"}}
    return claim


def make_project(root: Path, claims: list[dict]) -> None:
    (root / "claims").mkdir(parents=True)
    (root / "schemas").mkdir()
    shutil.copy(ROOT / "schemas" / "evidence-claim.v1.json", root / "schemas")
    for c in claims:
        (root / "claims" / f"{c['metadata']['name']}.yaml").write_text(yaml.safe_dump(c), encoding="utf-8")
    (root / "catalog.yaml").write_text(yaml.safe_dump_all(CATALOG), encoding="utf-8")
    (root / "config.toml").write_text(
        '[site]\nrepo = "Owner/Repo"\nsystem = "system:default/sys"\n[sources]\nclaims = ["claims"]\n'
        'catalog = ["catalog.yaml"]\nresearch = "research"\ncontent = "content"\n'
        'schema = "schemas/evidence-claim.v1.json"\n[labels]\nprioritise = ["research:prioritise"]\nreject = ["research:reject"]\n'
        'dispute = ["research:question"]\nquestion = ["research:question"]\n', encoding="utf-8")
    research = root / "research"
    research.mkdir()
    (research / "queue.json").write_text(json.dumps({"date": "2026-11-27", "how": "bits / hours", "queue": [
        {"claim": "hostile-claim", "role": "component:default/role-x", "about": "component:default/opt-x",
         "p_transfer": 0.4, "information_bits": 0.971, "cost_hours": 2.5, "score": 0.388,
         "plan": "Run it " + HOSTILE, "reason": "R " + HOSTILE, "prioritised_by": ["someone"],
         "rejected_by": [], "disputed_by": []}]}), encoding="utf-8")
    (research / "watch.yaml").write_text(yaml.safe_dump({"topics": [
        {"name": "topic-x", "question": "Q " + HOSTILE, "roles": ["role-x"], "terms": ["t1"]}]}), encoding="utf-8")
    (research / "seen.jsonl").write_text(json.dumps(
        {"id": "2611.00001", "title": "P " + HOSTILE, "status": "cataloged", "abstract": "A " + HOSTILE}) + "\n",
        encoding="utf-8")
    content = root / "content"
    (content / "notes").mkdir(parents=True)
    (content / "notes" / "hostile.md").write_text(
        "---\ntitle: A note\nkind: note\ndate: 2026-11-27\nrefs: [claim:two-setups, resource:big-model, trial:T-1]\n---\n"
        "Some *text*.\n", encoding="utf-8")


def run_build(out: Path, config: Path | None = None, base: str = "") -> subprocess.CompletedProcess:
    """`npm run build` with the contract's variables (site/README.md); `morphogen site build` sets the same."""
    env = dict(os.environ, MORPHOGEN_SITE_OUT=str(out), MORPHOGEN_SITE_BASE=base, ASTRO_TELEMETRY_DISABLED="1")
    env.pop("MORPHOGEN_SITE_CONFIG", None)
    if config is not None:
        env["MORPHOGEN_SITE_CONFIG"] = str(config)
    return subprocess.run(["npm", "run", "--silent", "build", "--", "--force"], cwd=SITE, env=env,
                          capture_output=True, text=True, timeout=600)


def built(out: Path, **kw) -> None:
    r = run_build(out, **kw)
    if r.returncode != 0:
        raise AssertionError(f"site build failed:\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")


def all_html(out: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(out.rglob("*.html")))


def read(out: Path, rel: str) -> str:
    return (out / rel).read_text(encoding="utf-8")


def issue_links(page: str) -> list[str]:
    return [html.unescape(h) for h in re.findall(r'href="(https://github\.com/[^"]+/issues/new\?[^"]+)"', page)]


class _Toolchain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not READY:
            if REQUIRED:
                raise AssertionError("MORPHOGEN_SITE_TESTS=1 but site/node_modules is missing: run `npm ci` in site/")
            raise unittest.SkipTest("the site's build needs Node and `npm ci` in site/ (site/README.md)")


class Unit(_Toolchain):
    def test_node_unit_tests(self):
        r = subprocess.run(["npm", "test", "--silent"], cwd=SITE, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)


class RealInput(_Toolchain):
    """The claims in demos/research-loop, through site/config.toml and site/content."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "out"
        built(cls.out)
        cls.graph = json.loads(read(cls.out, "data/graph.json"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_claim_has_a_page_and_a_feed_entry(self):
        names = set(self.graph["claims"])
        files = list((ROOT / "demos" / "research-loop" / "claims").rglob("*.yaml"))
        self.assertGreaterEqual(len(names), 25)
        self.assertEqual(len(names), len(files))
        self.assertEqual(self.graph["index_problems"], [])  # research/index.json agrees with the files
        self.assertEqual(self.graph["unresolved"], [])
        self.assertEqual({p.stem for p in (self.out / "claims").glob("*.html")}, names)
        index = read(self.out, "index.html")
        self.assertEqual(set(re.findall(r'<li class="item" data-name="([^"]+)"', index)), names)
        for page in ("roles.html", "predictions.html", "queue.html", "how.html", "map.html", "search.html",
                     "notes.html", "assets/style.css", "assets/site.js", "assets/vendor/alpine-csp.min.js",
                     "data/search.json", ".nojekyll"):
            self.assertTrue((self.out / page).exists(), page)
        self.assertEqual(len(json.loads(read(self.out, "data/claims.json"))["claims"]), len(names))

    def test_every_entity_has_a_page(self):
        for node in self.graph["nodes"]:
            self.assertTrue((self.out / node["url"]).is_file(), node["id"])
        types = {n["type"] for n in self.graph["nodes"]}
        self.assertLessEqual({"claim", "role", "option", "resource", "trial", "paper", "system", "page"}, types)

    def test_statuses_come_from_the_assessments(self):
        claims = self.graph["claims"]
        gates = claims["gates-likelihood-readout-27-31b-matches-jev"]
        self.assertEqual(gates["status"], "mixed")
        self.assertEqual(set(gates["statuses"]), {"did-not-transfer", "replicated"})
        self.assertEqual(claims["gates-embedding-logreg-labelled"]["status"], "predicted")
        self.assertEqual(claims["e04a-lfm3-pooled-accuracy"]["status"], "observation")
        roles = read(self.out, "roles.html")
        for role in ("decision-backend", "readout-calibration", "think-router"):
            self.assertIn(f'id="{role}"', roles)

    def test_a_model_lists_the_claims_tested_with_it(self):
        """The question that started this: was Inkling tested against the 27B+ finding, or only LFM3?"""
        page = read(self.out, "resources/inkling-2-mini-q4-k.html")
        row = re.search(r'<tr>(?:(?!</tr>).)*gates-likelihood-readout-27-31b-matches-jev\.html.*?</tr>', page, re.S).group(0)
        self.assertIn("Replicated", row)
        self.assertIn('href="../trials/e-04a.html"', row)
        self.assertIn("../claims/e04a-inkling-pooled-accuracy.html", page)  # our own measurement on it
        self.assertIn("../notes/2026-11-27-inkling-and-the-27b-finding.html", page)  # a note that names it

    def test_a_trial_lists_its_outcomes_and_models(self):
        page = read(self.out, "trials/e-04a.html")
        self.assertIn("../claims/gates-likelihood-readout-27-31b-matches-jev.html", page)
        self.assertIn("../resources/inkling-2-mini-q4-k.html", page)
        self.assertIn("../resources/lfm3-1.7b-q6-k.html", page)
        self.assertIn("../claims/e04a-lfm3-pooled-accuracy.html", page)

    def test_claim_page_has_a_tested_on_table_and_backlinks(self):
        page = read(self.out, "claims/gates-likelihood-readout-27-31b-matches-jev.html")
        table = re.search(r'<table class="tbl results">.*?</table>', page, re.S).group(0)
        self.assertIn("<strong>Inkling 2 Mini</strong>", table)
        self.assertIn("<strong>LFM3 1.7B</strong>", table)
        self.assertIn("../papers/arxiv-2610.00346.html", page)
        self.assertIn("Linked from", page)

    def test_paper_and_role_pages(self):
        paper = read(self.out, "papers/arxiv-2610.00346.html")
        self.assertIn("../claims/gates-embedding-logreg-labelled.html", paper)
        role = read(self.out, "roles/table-qa.html")
        self.assertIn("Open questions the agent watches", role)
        self.assertIn("../options/capability-aware-table-routing.html", role)

    def test_no_outside_resources_and_no_inline_script(self):
        text = all_html(self.out)
        self.assertNotRegex(text, r'<(script|link)[^>]+(src|href)="https?://')
        self.assertNotRegex(text, r"<script(?![^>]*\ssrc=)[^>]*>", "inline scripts would break the content security policy")
        self.assertNotIn(" style=", text)
        self.assertNotIn("unsafe-eval", text)
        self.assertNotIn("unsafe-inline", text)

    def test_issue_links_in_the_pages_are_well_formed(self):
        links = issue_links(read(self.out, "claims/gates-embedding-logreg-labelled.html"))
        self.assertEqual(len(links), 3)  # prioritise, reject, dispute (it has a prediction)
        for url in links:
            parts = urlsplit(url)
            self.assertEqual((parts.scheme, parts.netloc, parts.path), ("https", "github.com", "/OpenReplicant/Morphogen/issues/new"))
            q = parse_qs(parts.query, strict_parsing=True)
            self.assertEqual(set(q), {"title", "body", "labels"})
            body = q["body"][0]
            self.assertIn("research-claim: gates-embedding-logreg-labelled", body)
            self.assertIn("\nresearch-action: ", body)
            self.assertIn("\nclaim-file: https://github.com/OpenReplicant/Morphogen/blob/main/demos/research-loop/claims/", body)
            self.assertTrue(q["labels"][0].startswith("research:"))
            self.assertLess(len(url), 8000)


class Fixture(_Toolchain):
    """A project of its own: a hostile claim, a claim tried on two configurations, a scored one, and the agent's files."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        make_project(cls.root, [CLAIM, two_setups(), scored()])
        cls.out = cls.root / "out"
        built(cls.out, config=cls.root / "config.toml")
        cls.graph = json.loads(read(cls.out, "data/graph.json"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_text_from_files_is_escaped(self):
        raw = all_html(self.out)
        # Astro escapes & and " inside a quoted attribute value (where < cannot open a tag) and &, < and > in text:
        # with every quoted value taken out, no markup from a file may remain.
        text = re.sub(r'="[^"]*"', '=""', raw)
        self.assertNotIn("<script>alert", text)
        self.assertNotIn("<img src=x", text)
        self.assertNotIn("<b>beats</b>", text)
        self.assertIn("&lt;script&gt;alert(", text)
        self.assertIn('content="X beats Y <script>alert(&quot;x&quot;)', raw)  # the quote is escaped in the attribute
        self.assertNotRegex(raw, r'href="\s*javascript:', "a javascript: URL from a file was written as a link")
        page = read(self.out, "claims/hostile-claim.html")
        self.assertIn("A paper &lt;script&gt;", page)  # the title is still shown, as text
        for url in issue_links(page):  # and paper text stays out of issue bodies (they render as Markdown)
            self.assertNotIn("alert", url)

    def test_actions_the_agent_reads(self):
        """Every button's body names one of the agent's actions (morphogen/research.py, ACTIONS)."""
        actions = set()
        for url in issue_links(all_html(self.out)):
            body = parse_qs(urlsplit(url).query)["body"][0]
            actions |= set(re.findall(r"^research-action: (\S+)$", body, re.M))
        self.assertEqual(actions, {"prioritise", "reject", "dispute", "question", "propose-role", "propose-option"})

    def test_queue_watch_and_trial_plan(self):
        queue = read(self.out, "queue.html")
        self.assertIn('href="claims/hostile-claim.html"', queue)
        self.assertIn("prioritised by someone", queue)
        self.assertIn("0.388", queue)
        page = read(self.out, "claims/hostile-claim.html")
        self.assertIn("The cheapest trial that would settle it", page)
        self.assertIn("about 2.5 hours", page)
        self.assertIn("Number 1 of 1 in the", page)
        roles = read(self.out, "roles.html")
        self.assertIn("topic-x", roles)
        self.assertIn("Papers seen", roles)
        self.assertIn("topic-x", read(self.out, "roles/role-x.html"))

    def test_mixed_status_with_both_results(self):
        c = self.graph["claims"]["two-setups"]
        self.assertEqual(c["status"], "mixed")
        self.assertEqual(c["statuses"], ["did-not-transfer", "replicated"])
        self.assertEqual(c["status_text"], "did-not-transfer (Small Model 1B); replicated (Big Model 26B)")
        index = read(self.out, "index.html")
        item = re.search(r'<li class="item" data-name="two-setups"[^>]*>.*?</li>', index, re.S).group(0)
        self.assertIn('data-status="did-not-transfer replicated"', item)
        for text in ("Mixed", "Did not transfer", "Replicated", "Small Model 1B", "Big Model 26B"):
            self.assertIn(text, item)
        page = read(self.out, "claims/two-setups.html")
        self.assertEqual(page.count('<div class="assess">'), 2)
        for text in ("Small model: far below.", "Big model: matched.", "on <strong>Small Model 1B</strong>",
                     "on <strong>Big Model 26B</strong>"):
            self.assertIn(text, page)
        body = parse_qs(urlsplit(issue_links(page)[0]).query)["body"][0]
        self.assertIn("status: did-not-transfer (Small Model 1B); replicated (Big Model 26B)", body)

    def test_each_prediction_is_scored(self):
        pairs = sorted((x["claim"], x["p"], x["held"]) for x in self.graph["calibration"]["pairs"])
        self.assertEqual(pairs, [("scored-claim", 0.4, 0), ("two-setups", 0.3, 0), ("two-setups", 0.7, 1)])
        self.assertAlmostEqual(self.graph["calibration"]["brier"], (0.16 + 0.09 + 0.09) / 3)
        page = read(self.out, "predictions.html")
        self.assertIn("<strong>3</strong> predictions", page)
        self.assertIn('Brier score <strong class="mono">0.113</strong>', page)
        self.assertIn('<g class="dot">', page)

    def test_models_trials_and_notes_link_back(self):
        big = read(self.out, "resources/big-model.html")
        self.assertIn("../claims/two-setups.html", big)
        self.assertIn("../notes/hostile.html", big)
        trial = read(self.out, "trials/t-1.html")
        self.assertIn("../resources/small-model.html", trial)
        self.assertIn("../resources/big-model.html", trial)
        self.assertIn("../claims/two-setups.html", read(self.out, "notes/hostile.html"))


class BrokenInput(_Toolchain):
    def test_invalid_claim_stops_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            bad = copy.deepcopy(CLAIM)
            bad["spec"]["assessments"][0]["status"] = "probably-fine"
            make_project(root, [bad])
            r = run_build(root / "out", config=root / "config.toml")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("not a valid EvidenceClaim", r.stdout + r.stderr)

    def test_a_page_naming_a_missing_entity_stops_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_project(root, [CLAIM])
            (root / "content" / "bad.md").write_text("---\ntitle: Bad\nrefs: [resource:nowhere]\n---\nx\n", encoding="utf-8")
            r = run_build(root / "out", config=root / "config.toml")
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("refers to resource:nowhere", r.stdout + r.stderr)


ORCHARD_CLAIM = {
    "apiVersion": "morphogen.dev/v1alpha1",
    "kind": "EvidenceClaim",
    "metadata": {"name": "pruning-raises-yield", "description": "Summer pruning raises yield"},
    "spec": {
        "about": "component:default/summer-pruning",
        "role": "component:default/canopy",
        "source": {"kind": "preprint", "title": "Pruning and yield", "id": "arXiv:2611.00042",
                   "url": "https://arxiv.org/abs/2611.00042", "version": "v1", "location": "Table 2",
                   "read": "in full", "quote": "yield rose", "quote_status": "checked"},
        "claim": {"statement": "Summer pruning raises yield", "finding": "better", "reporting": "self",
                  "metric": "kg per tree", "value": 41, "baseline": {"name": "no pruning", "value": 35}},
        "conditions": {"unstated": ["rootstock"]},
        "assessments": [{"system": "system:default/orchard", "status": "predicted", "date": "2026-11-27",
                         "prediction": {"p_transfer": 0.6, "reason": "Same climate", "by": "test",
                                        "date": "2026-11-27", "before_outcome": True}}],
    },
}
ORCHARD_CATALOG = [
    {"apiVersion": "backstage.io/v1alpha1", "kind": "System", "metadata": {"name": "orchard"},
     "spec": {"owner": "group:default/growers"}},
    {"apiVersion": "backstage.io/v1alpha1", "kind": "Component", "metadata": {"name": "canopy"},
     "spec": {"type": "role", "lifecycle": "production", "owner": "group:default/growers", "system": "system:default/orchard"}},
    {"apiVersion": "backstage.io/v1alpha1", "kind": "Component", "metadata": {"name": "summer-pruning"},
     "spec": {"type": "method", "lifecycle": "candidate", "owner": "group:default/growers",
              "morphogen": {"fills": "component:default/canopy"}}},
]


class AnotherSystem(_Toolchain):
    """Anyone's system: `morphogen site init` in a made-up project (another system, other labels, a theme, fewer
    pages in the header), built with `morphogen site build --base /lab`. Nothing of Morphogen's demo may show."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        from morphogen import site
        cls.tmp = tempfile.TemporaryDirectory()
        root = cls.root = Path(cls.tmp.name) / "grove"
        (root / "claims").mkdir(parents=True)
        (root / "claims" / "pruning.yaml").write_text(yaml.safe_dump(ORCHARD_CLAIM), encoding="utf-8")
        (root / "catalog-info.yaml").write_text(yaml.safe_dump(ORCHARD_CATALOG[0]), encoding="utf-8")
        (root / "catalog").mkdir()
        (root / "catalog" / "map.yaml").write_text(yaml.safe_dump_all(ORCHARD_CATALOG[1:]), encoding="utf-8")
        made = site.init(root, repo="Growers/grove", title="Grove lab", owner="The Growers")
        assert made["system"] == "system:default/orchard", made  # read from catalog-info.yaml
        cfg = Path(made["config"])
        text = cfg.read_text(encoding="utf-8")
        for old, new in (('"research:prioritise"', '"grove:boost"'), ('"research:reject"', '"grove:drop"'),
                         ('# css = "site-theme.css"', 'css = "brand/theme.css"'), ('# logo = "logo.svg"', 'logo = "brand/logo.svg"'),
                         ('pages = ["claims", "queue", "predictions", "roles", "map", "notes"]', 'pages = ["claims", "roles", {page = "search", text = "Find"}]')):
            assert old in text, old
            text = text.replace(old, new)
        cfg.write_text(text, encoding="utf-8")
        (root / "brand").mkdir()
        (root / "brand" / "theme.css").write_text(":root { --accent: #2a7; }\n", encoding="utf-8")
        (root / "brand" / "logo.svg").write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding="utf-8")
        cls.out = Path(cls.tmp.name) / "public"
        r = subprocess.run([sys.executable, "-m", "morphogen", "site", "build", "--config", str(cfg), "--out",
                            str(cls.out), "--base", "/lab"], cwd=cls.tmp.name, capture_output=True, text=True, timeout=600)
        if r.returncode:
            raise AssertionError(f"morphogen site build failed:\n{r.stdout[-3000:]}\n{r.stderr[-3000:]}")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_it_is_their_site(self):
        text = all_html(self.out)
        self.assertNotIn("Morphogen research", text)
        self.assertNotIn("metasoar", text.lower())
        self.assertNotIn("demos/research-loop", text)
        index = read(self.out, "index.html")
        self.assertIn("<title>Grove lab</title>", index)
        self.assertIn("The Growers", index)
        self.assertTrue((self.out / "claims" / "pruning-raises-yield.html").is_file())
        self.assertTrue((self.out / "about.html").is_file())  # the starter content folder

    def test_steering_goes_to_their_repo_with_their_labels(self):
        links = issue_links(read(self.out, "claims/pruning-raises-yield.html"))
        self.assertEqual(len(links), 3)
        labels = set()
        for url in links:
            parts = urlsplit(url)
            self.assertEqual(parts.path, "/Growers/grove/issues/new")
            q = parse_qs(parts.query, strict_parsing=True)
            self.assertIn("\nsystem: system:default/orchard", q["body"][0])
            self.assertIn("\nclaim-file: https://github.com/Growers/grove/blob/main/claims/pruning.yaml", q["body"][0])
            labels.add(q["labels"][0])
        self.assertEqual(labels, {"grove:boost", "grove:drop", "research:question"})

    def test_every_link_and_asset_is_under_the_base(self):
        n = 0
        for f in self.out.rglob("*.html"):
            page = "/lab/" + f.relative_to(self.out).as_posix()
            for u in re.findall(r'\s(?:href|src)="([^"]*)"', f.read_text(encoding="utf-8")):
                if u.startswith(("https://", "http://", "#")):
                    continue
                n += 1
                target = urlsplit(urljoin("http://host" + page, html.unescape(u))).path
                self.assertTrue(target.startswith("/lab/"), f"{page}: {u}")
                self.assertTrue((self.out / target[len("/lab/"):]).is_file(), f"{page}: {u} -> {target}")
        self.assertGreater(n, 50)
        self.assertIn('href="/lab/claims/pruning-raises-yield.html"', read(self.out, "index.html"))
        self.assertIn('data-index="/lab/data/search.json"', read(self.out, "search.html"))

    def test_theme_and_navigation(self):
        index = read(self.out, "index.html")
        self.assertIn('<link rel="stylesheet" href="/lab/assets/user/theme.css">', index)
        self.assertIn('src="/lab/assets/user/logo.svg"', index)
        self.assertEqual(read(self.out, "assets/user/theme.css"), ":root { --accent: #2a7; }\n")
        nav = re.search(r'<nav aria-label="Site"><ul>(.*?)</ul></nav>', index).group(1)
        self.assertEqual(re.findall(r">([^<]+)</a>", nav), ["Claims", "Roles", "Find", "About this site"])
        self.assertTrue((self.out / "queue.html").is_file())  # left out of the header, still built


class Init(unittest.TestCase):
    def test_init_refuses_to_overwrite_and_needs_a_system(self):
        from morphogen import site
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(site.SiteError, "--system"):
                site.init(tmp, repo="A/b")
            site.init(tmp, repo="A/b", system="mine")
            self.assertIn('system = "system:default/mine"', (Path(tmp) / "site.toml").read_text(encoding="utf-8"))
            with self.assertRaisesRegex(site.SiteError, "exists"):
                site.init(tmp, repo="A/b", system="mine")
            with self.assertRaisesRegex(site.SiteError, "OWNER/NAME"):
                site.init(tmp, repo="not a repo", system="mine", force=True)


if __name__ == "__main__":
    unittest.main()
