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
        'dispute = ["research:question"]\nquestion = ["research:question"]\n'
        '[nav]\npages = ["claims", "queue", {text = "Home", href = "/"}, {text = "Docs", href = "https://example.org/docs?a=1&b=2"},'
        ' {text = "Local", href = "about.html"}]\n'
        '[funding]\nurl_template = "https://example.org/fund/{id}/"\nlabel = "Back this"\n', encoding="utf-8")
    research = root / "research"
    research.mkdir()
    (research / "queue.json").write_text(json.dumps({"date": "2026-11-27", "how": "bits / hours", "queue": [
        {"claim": "hostile-claim", "role": "component:default/role-x", "about": "component:default/opt-x",
         "p_transfer": 0.4, "information_bits": 0.971, "cost_hours": 2.5, "score": 0.388,
         "plan": "Run it " + HOSTILE, "reason": "R " + HOSTILE, "prioritised_by": ["someone"],
         "rejected_by": [], "disputed_by": [], "currency": "USD", "cost_money": 30.0, "pledged": 10.0, "received": 0.0,
         "funded_fraction": 0.3333, "funding_source": "Src " + HOSTILE, "ready": True},
        {"claim": "scored-claim", "role": "component:default/role-x", "about": "component:default/opt-x",
         "p_transfer": 0.5, "information_bits": 1.0, "cost_hours": 1.0, "score": 1.0, "plan": "Plain",
         "prioritised_by": [], "rejected_by": [], "disputed_by": [], "currency": "USD", "cost_money": None,
         "pledged": 0.0, "received": 0.0, "funded_fraction": 0.0, "funding_source": None, "ready": False}]}),
        encoding="utf-8")
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
        self.assertIn("Number 1 of 2 in the", page)
        roles = read(self.out, "roles.html")
        self.assertIn("topic-x", roles)
        self.assertIn("Papers seen", roles)
        self.assertIn("topic-x", read(self.out, "roles/role-x.html"))

    def test_funding_on_the_queue_and_beside_the_plan(self):
        queue = read(self.out, "queue.html")
        self.assertEqual(queue.count('class="funding"'), 1)  # the row without a price shows nothing
        self.assertIn("33% funded", queue)
        self.assertIn("30 USD", queue)
        self.assertIn('class="tag tag-ready">ready<', queue)
        self.assertIn('href="https://example.org/fund/hostile-claim/" rel="noopener">Back this</a>', queue)
        page = read(self.out, "claims/hostile-claim.html")
        self.assertIn("33% funded", page)
        self.assertIn("Back this", page)
        self.assertNotIn("funded", read(self.out, "claims/scored-claim.html"))
        # funding_source is free text: it is escaped like any other
        text = re.sub(r'="[^"]*"', '=""', queue + page)
        self.assertIn("Source: Src ", text)
        self.assertNotIn("<script>alert", text)
        self.assertNotIn("<b>beats</b>", text)

    def test_external_links_in_the_header(self):
        index = read(self.out, "index.html")
        nav = re.search(r'<nav aria-label="Site"><ul>(.*?)</ul></nav>', index).group(1)
        self.assertEqual(re.findall(r">([^<]+)</a>", nav), ["Claims", "Next to test", "Home", "Docs", "Local"])
        self.assertIn('<a href="/">Home</a>', nav)
        self.assertIn('<a href="https://example.org/docs?a=1&amp;b=2" rel="noopener">Docs</a>', nav)
        self.assertIn('<a href="about.html">Local</a>', nav)
        deep = re.search(r'<nav aria-label="Site"><ul>(.*?)</ul></nav>', read(self.out, "claims/hostile-claim.html")).group(1)
        self.assertIn('<a href="../about.html">Local</a>', deep)
        self.assertIn('<a href="/">Home</a>', deep)

    def test_external_links_respect_the_base_only_when_relative(self):
        out = self.root / "out-base"
        built(out, config=self.root / "config.toml", base="/lab")
        nav = re.search(r'<nav aria-label="Site"><ul>(.*?)</ul></nav>', read(out, "claims/hostile-claim.html")).group(1)
        self.assertIn('<a href="/">Home</a>', nav)
        self.assertIn('href="https://example.org/docs?a=1&amp;b=2" rel="noopener"', nav)
        self.assertIn('<a href="/lab/about.html">Local</a>', nav)
        self.assertIn('<a href="/lab/queue.html"', nav)

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
                         ('pages = ["claims", "queue", "predictions", "roles", "map", "catalog", "optimise", "notes"]', 'pages = ["claims", "roles", {page = "search", text = "Find"}]')):
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


class BadNav(_Toolchain):
    def test_javascript_link_and_bad_funding_template_stop_the_build(self):
        for extra in ('[nav]\npages = [{text = "x", href = "javascript:alert(1)"}]\n',
                      '[nav]\npages = [{href = "/"}]\n',
                      '[funding]\nurl_template = "javascript:alert(\'{id}\')"\n',
                      '[funding]\nurl_template = "https://example.org/fund/"\n'):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                make_project(root, [CLAIM])
                cfg = root / "config.toml"
                text = cfg.read_text(encoding="utf-8")
                text = text[:text.index("[nav]")]  # drop the fixture's own [nav] and [funding]
                cfg.write_text(text + extra, encoding="utf-8")
                self.assertNotEqual(run_build(root / "out", config=cfg).returncode, 0, extra)


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


def project_config(root: Path, extra_sources: str = "", pages: str = '["map", "catalog", "optimise", "search"]') -> Path:
    cfg = root / "site.toml"
    cfg.write_text('[site]\nrepo = "Owner/Repo"\nsystem = "system:default/shop"\n[sources]\n'
                   f'catalog = ["catalog-info.yaml"]\n{extra_sources}\n[nav]\npages = {pages}\n', encoding="utf-8")
    return cfg


SHOP = [
    {"apiVersion": "backstage.io/v1alpha1", "kind": "System", "metadata": {"name": "shop", "description": "A shop " + HOSTILE},
     "spec": {"owner": "group:default/team", "morphogen": {"autonomy": {"experimental": "merge"}}}},
    {"apiVersion": "backstage.io/v1alpha1", "kind": "Group", "metadata": {"name": "team", "title": "The team"}, "spec": {"type": "team"}},
    {"apiVersion": "backstage.io/v1alpha1", "kind": "Component", "metadata": {"name": "pricing", "description": "Prices " + HOSTILE},
     "spec": {"type": "library", "lifecycle": "production", "owner": "group:default/team", "system": "shop",
              "providesApis": ["price-list"], "consumesApis": ["catalog-feed"], "dependsOn": ["resource:default/db"],
              "morphogen": {"description": "Quote closer to cost " + HOSTILE, "dir": "pricing", "run": "python bench.py",
                            "change": ["pricing/p.py#MARKUP in 0.1..0.6", "prompts/"], "keep": ["pricing/p.py#RATE"],
                            "better": {"mape": {"lower": True}}, "score": "python score.py", "tests": "python -m unittest -q",
                            "observe": "otel"}}},
    {"apiVersion": "backstage.io/v1alpha1", "kind": "Component", "metadata": {"name": "checkout", "description": "Takes the order"},
     "spec": {"type": "service", "lifecycle": "production", "owner": "user:default/ann", "system": "shop",
              "consumesApis": ["price-list"], "dependsOn": ["resource:default/db"]}},
    {"apiVersion": "backstage.io/v1alpha1", "kind": "API", "metadata": {"name": "price-list", "description": "Price per item"},
     "spec": {"type": "openapi", "lifecycle": "production", "owner": "group:default/team", "definition": "contracts/prices.md",
              "morphogen": {"tests": "python -m unittest -q contracts", "external": "consumes"}}},
    {"apiVersion": "backstage.io/v1alpha1", "kind": "API", "metadata": {"name": "catalog-feed"}, "spec": {"type": "grpc"}},
    {"apiVersion": "backstage.io/v1alpha1", "kind": "Resource", "metadata": {"name": "db", "description": "The orders database"},
     "spec": {"type": "database", "owner": "group:default/team"}},
    {"apiVersion": "backstage.io/v1alpha1", "kind": "Component", "metadata": {"name": "payments", "description": "Take payment"},
     "spec": {"type": "role", "lifecycle": "production", "owner": "group:default/team", "system": "shop", "consumesApis": ["price-list"]}},
    {"apiVersion": "backstage.io/v1alpha1", "kind": "Component", "metadata": {"name": "stripe", "description": "Stripe " + HOSTILE},
     "spec": {"type": "service", "lifecycle": "candidate", "owner": "group:default/team", "system": "shop", "providesApis": ["catalog-feed"],
              "morphogen": {"fills": "component:default/payments", "licence": "proprietary " + HOSTILE,
                            "docs": {"url": "javascript:alert(1)"},
                            "parameters": {"type": "object", "properties": {"retries": {"type": "integer", "minimum": 0, "maximum": 5, "default": 2,
                                                                                    "description": "Attempts " + HOSTILE}}},
                            "evaluation": {"result": "p95 120 ms " + HOSTILE}}}},
    {"apiVersion": "backstage.io/v1alpha1", "kind": "Component", "metadata": {"name": "paypal", "description": "PayPal"},
     "spec": {"type": "service", "lifecycle": "candidate", "owner": "group:default/team", "system": "shop",
              "morphogen": {"fills": "component:default/payments", "licence": "MIT", "docs": {"url": "https://example.org/paypal"}}}},
]


def judge_log(path: Path, tamper: bool = False) -> None:
    """A verdict log as `morphogen evidence` prints it: records through the real hash-chained log, in the shapes
    morphogen/judge.py writes them (a pass with measures, a refusal with its reasons, a probe, a change check)."""
    from morphogen.evidence import Evidence
    ev = Evidence(path.with_suffix(".db"))
    base, cand = "a" * 40, "b" * 40
    common = {"kind": "verdict", "trust": "measured", "by": "judge", "refs": {"base": base, "candidate": cand}, "sandbox": "podman"}
    ev.append({**common, "claim": "pricing: bbbbbbbbbbbb is better than aaaaaaaaaaaa " + HOSTILE, "verdict": "pass",
               "subject": {"system": "pricing", "path": "cell:pricing"}, "cell": "pricing", "gate": {"decision": "review"},
               "parameters": {"p.py#MARKUP": {"owner": "agent", "base": 0.2, "candidate": 0.35}},
               "outcome": {"check": True, "generated_inputs": 40, "wrong": 0, "failed": 0, "timed_output_mismatches": 0,
                           "metrics": {"mape": {"base": 0.124, "candidate": 0.034, "gain": 0.72, "ci95": [0.5, 0.8],
                                                "sign_test_p": 0.008, "ok": True}}}})
    ev.append({**common, "claim": "pricing: cccc is not better", "verdict": "fail", "refs": {"base": base, "candidate": "c" * 40},
               "subject": {"system": "pricing", "path": "cell:pricing"}, "cell": "pricing", "gate": {"decision": "none"},
               "parameters": {"p.py#MARKUP": {"owner": "agent", "base": 0.35, "candidate": 0.9}},
               "outcome": {"check": True, "denied": ["tests/t.py: outside what the cell may change " + HOSTILE],
                           "parameter_violations": ["sets MARKUP to 0.9, outside its range [0.1, 0.6]"],
                           "metrics": {"mape": {"base": 0.034, "candidate": 0.05, "gain": -0.4, "ci95": [-0.6, -0.1],
                                                "sign_test_p": 0.5, "ok": False}}}})
    ev.append({"kind": "probe", "claim": "probe of bbbb (practice; not a verdict)", "trust": "measured", "by": "judge",
               "subject": {"system": "pricing"}, "outcome": {}})
    ev.append({**common, "claim": "change dddd keeps what checkout promises", "verdict": "pass", "cells": ["checkout"],
               "subject": {"system": "checkout", "path": "change"}, "gate": {"decision": "merge"},
               "outcome": {"files": {"checkout/a.py": ["checkout"]}, "denied": [], "tests": [{"cell": "checkout", "test": "t", "passed": True}]},
               "signature": "sig:" + HOSTILE, "transparency": {"log_index": 7, "log": "rekor.example"}})
    ev.append({**common, "claim": "elsewhere: a verdict on a cell not in the map", "verdict": "fail", "cell": "ghost",
               "subject": {"system": "ghost"}, "gate": {"decision": "none"}, "outcome": {"check": False}})
    rows = ev.query(limit=100)  # newest first, as the command prints it
    if tamper:
        rows[1]["claim"] = "edited afterwards"
    path.write_text(json.dumps(rows, indent=2), encoding="utf-8")


class Optimise(_Toolchain):
    """The Optimise page: the cells, the judge's verdict log for each, and the evidence chain."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        (cls.root / "catalog-info.yaml").write_text(yaml.safe_dump_all(SHOP), encoding="utf-8")
        judge_log(cls.root / "verdicts.json")
        cfg = project_config(cls.root, 'verdicts = "verdicts.json"')
        cls.out = cls.root / "out"
        built(cls.out, config=cfg)
        cls.page = read(cls.out, "optimise.html")
        cls.text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", cls.page.split("<main", 1)[1])))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_cell_says_what_may_change_how_it_is_scored_and_who_merges(self):
        t = self.text
        self.assertIn("Cells (1)", t)  # pricing only: checkout has no `run`, the role and options are never cells
        self.assertIn("pricing/p.py#MARKUP within 0.1..0.6", t)
        self.assertIn("prompts/", t)
        self.assertIn("Held fixed: pricing/p.py#RATE", t)
        self.assertIn("mape lower", t)
        self.assertIn("python score.py", t)
        self.assertIn("a person reviews", t)  # production is not in the System's autonomy list for merge
        self.assertIn("otel", t)
        self.assertIn("owned by team", t)

    def test_each_verdict_is_listed_under_its_cell_with_measures_and_reasons(self):
        t = self.text
        self.assertIn("Verdicts on pricing (2)", t)
        self.assertEqual(self.page.count('class="verdict"'), 4)  # pricing 2, checkout 1 and ghost 1; the probe is no verdict
        self.assertRegex(t, r"Refused #2 .*Passed #1")  # newest first
        self.assertIn("commit bbbbbbbbbbbb against base aaaaaaaaaaaa", t)
        self.assertIn("Settings moved: p.py#MARKUP 0.2 to 0.35", t)
        self.assertIn("0.124 0.034 +72.0%", t)  # measures: base, candidate, gain
        self.assertIn("every measure met its bar", t)
        self.assertIn("sets MARKUP to 0.9, outside its range [0.1, 0.6]", t)
        self.assertIn("mape: gain -40.0% (95% interval -60.0% to -10.0%, sign test p=0.5) does not meet the bar", t)
        self.assertIn("changes what the cell may not change: tests/t.py: outside what the cell may change", t)
        self.assertIn("Verdicts on ghost (1)", t)
        self.assertIn("not a cell in this site's map", t)

    def test_observed_comes_from_the_judges_last_measure(self):
        self.assertRegex(self.text, r"Observed mape 0\.034 to 0\.05 \(-40\.0%\) in verdict #2 \(refused\)")

    def test_the_evidence_chain_and_a_signature(self):
        t = self.text
        self.assertIn("The evidence chain", t)
        self.assertIn("The records read here: 5, numbered 1 to 5, from the first record of the log", t)
        self.assertRegex(t, r"Links intact")
        self.assertIn("sig:", t)  # a signature a record carries is shown, as text
        self.assertIn("log_index", t)
        self.assertNotIn("<script>alert", re.sub(r'="[^"]*"', '=""', all_html(self.out)))

    def test_the_header_lists_optimise_and_the_map_marks_the_cell(self):
        index = read(self.out, "index.html")
        nav = re.search(r'<nav aria-label="Site"><ul>(.*?)</ul></nav>', index).group(1)
        self.assertEqual(re.findall(r">([^<]+)</a>", nav), ["Map", "Catalog", "Optimise", "Search"])
        self.assertIn('class="tag tag-ready" href="optimise.html">cell', read(self.out, "map.html"))

    def test_a_log_edited_afterwards_shows_a_break(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "catalog-info.yaml").write_text(yaml.safe_dump_all(SHOP), encoding="utf-8")
            judge_log(root / "verdicts.json", tamper=True)
            built(root / "out", config=project_config(root, 'verdicts = "verdicts.json"'))
            page = read(root / "out", "optimise.html")
            self.assertRegex(page, r"1 do not match: #4")
            self.assertNotIn("all recomputed", page)

    def test_cells_without_a_log_say_what_is_missing_and_show_no_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "catalog-info.yaml").write_text(yaml.safe_dump_all(SHOP), encoding="utf-8")
            built(root / "out", config=project_config(root))
            page = read(root / "out", "optimise.html")
            self.assertIn("No verdicts to show", page)
            self.assertIn("morphogen evidence --limit 100000", page)
            self.assertNotIn('class="verdict"', page)
            self.assertNotIn("The evidence chain", page)


class SystemMap(_Toolchain):
    """Entities with interfaces: the map's graph and table, each entity's page, the catalog's compare table."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        (cls.root / "catalog-info.yaml").write_text(yaml.safe_dump_all(SHOP), encoding="utf-8")
        cls.out = cls.root / "out"
        built(cls.out, config=project_config(cls.root), base="/ui")
        cls.graph = json.loads(read(cls.out, "data/graph.json"))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_interfaces_owners_and_dependencies_become_references(self):
        rels = {(e["from"], e["to"], e["rel"]) for e in self.graph["edges"]}
        for edge in (("component:pricing", "api:price-list", "provides"), ("component:checkout", "api:price-list", "consumes"),
                     ("component:pricing", "resource:db", "depends-on"), ("component:pricing", "group:team", "owned-by"),
                     ("component:checkout", "group:ann", "owned-by")):  # `ann` has no file: an owner all the same
            self.assertIn(edge, rels)
        self.assertEqual(self.graph["unresolved"], [])

    def test_the_map_page_has_the_system_graph_and_a_row_per_entity(self):
        page = read(self.out, "map.html")
        self.assertIn('id="graph-system"', page)
        self.assertIn('href="/ui/apis/price-list.html"', page)
        row = re.search(r'<tr id="component-pricing">(.*?)</tr>', page, re.S).group(1)
        for want in ("/ui/owners/team.html", "price-list", "catalog-feed", "/ui/resources/db.html", ">cell<"):
            self.assertIn(want, row)
        dependents = re.search(r'<tr id="resource-db">(.*?)</tr>', page, re.S).group(1)
        self.assertIn("pricing", dependents)
        self.assertIn("checkout", dependents)

    def test_an_entity_page_shows_provides_consumes_owner_dependencies_and_dependents(self):
        page = read(self.out, "components/pricing.html")
        text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", page))
        for want in ("Interfaces and ownership", "Owner team", "Provides price-list", "Consumes catalog-feed", "Depends on The orders database"):
            self.assertIn(want, text)
        api = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", read(self.out, "apis/price-list.html")))
        self.assertIn("Provided by pricing", api)
        self.assertRegex(api, r"Consumed by .*checkout")
        self.assertIn("contracts/prices.md", api)
        self.assertIn("python -m unittest -q contracts", api)
        owner = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", read(self.out, "owners/ann.html")))
        self.assertIn("no Group or User file", owner)
        self.assertIn("checkout", owner)
        res = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", read(self.out, "resources/db.html")))
        self.assertIn("Dependents", res)

    def test_catalog_compares_the_options_for_a_role(self):
        page = read(self.out, "catalog.html")
        table = re.search(r"<table.*?</table>", page, re.S).group(0)
        for want in ("stripe", "paypal", "catalog-feed", "MIT", "proprietary", "retries", "https://example.org/paypal"):
            self.assertIn(want, table)
        self.assertNotRegex(page, r'href="\s*javascript:')  # the docs link that was not http(s) is text
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", page)))
        self.assertIn("Compare options for this role (2)", text)
        self.assertIn("retries integer 0 to 5 2", text)
        self.assertIn("The role's interfaces", text)
        self.assertNotIn("<script>alert", re.sub(r'="[^"]*"', '=""', all_html(self.out)))
        self.assertIn('href="/ui/', page)  # every link under the base


class ResearchOnly(Fixture):
    """A research-only site (claims, roles and options, no cell, no interface, no verdict log) still builds, and the
    pages that have nothing to show leave the header."""

    def test_no_optimise_and_no_system_map(self):
        optimise = read(self.out, "optimise.html")
        self.assertIn("Nothing here", optimise)
        self.assertNotIn("The evidence chain", optimise)
        self.assertNotIn('class="verdict"', optimise)
        page = read(self.out, "map.html")
        self.assertNotIn('id="graph-system"', page)
        self.assertIn('id="graph-research"', page)
        self.assertNotIn("Every part, with its interfaces", page)
        option = read(self.out, "options/opt-x.html")  # an owner, but no interface to show
        self.assertNotIn("<dt>Provides</dt>", option)
        self.assertNotIn("<dt>Consumes</dt>", option)

    def test_a_header_that_names_optimise_leaves_it_out(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            make_project(root, [CLAIM])
            cfg = root / "config.toml"
            text = cfg.read_text(encoding="utf-8")
            cfg.write_text(text[:text.index("[nav]")] + '[nav]\npages = ["claims", "catalog", "optimise"]\n', encoding="utf-8")
            shutil.rmtree(root / "content")  # the fixture's note names claims this project does not have
            built(root / "out", config=cfg)
            nav = re.search(r'<nav aria-label="Site"><ul>(.*?)</ul></nav>', read(root / "out", "index.html")).group(1)
            self.assertEqual(re.findall(r">([^<]+)</a>", nav), ["Claims", "Catalog"])  # the catalog has a role and an option


class Fernhill(_Toolchain):
    """demos/fernhill: a firm with no claims, one cell and no verdict log. It says what is missing and invents nothing."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "out"
        built(cls.out, config=ROOT / "demos" / "fernhill" / "site.toml")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_map_the_catalog_and_the_cell(self):
        self.assertIn("quote-calculator", read(self.out, "optimise.html"))
        self.assertIn("No verdicts to show", read(self.out, "optimise.html"))
        self.assertNotIn('class="verdict"', read(self.out, "optimise.html"))
        self.assertTrue((self.out / "components" / "quote-calculator.html").is_file())
        self.assertTrue((self.out / "apis" / "job-spec.html").is_file())
        catalog = read(self.out, "catalog.html")
        for option in ("fergus", "tradify", "servicem8", "shared-calendar"):
            self.assertTrue((self.out / "options" / f"{option}.html").is_file(), option)
            self.assertIn(option, catalog)
        self.assertIn("Compare options for this role (4)", re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", catalog)))
        self.assertIn('id="graph-system"', read(self.out, "map.html"))

    def test_the_header_has_no_research_pages(self):
        nav = re.search(r'<nav aria-label="Site"><ul>(.*?)</ul></nav>', read(self.out, "index.html")).group(1)
        self.assertEqual(re.findall(r">([^<]+)</a>", nav), ["Map", "Catalog", "Optimise", "Search"])
        self.assertNotIn('class="feed"', read(self.out, "index.html"))  # no claims: the home page is the four verbs


if __name__ == "__main__":
    unittest.main()
