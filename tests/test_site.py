"""The research site's build (site/build.py): real input renders, issue links are well formed, and text from papers
is escaped."""

import copy
import html
import importlib.util
import json
import re
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("site_build", ROOT / "site" / "build.py")
build = importlib.util.module_from_spec(_spec)
sys.modules["site_build"] = build  # dataclasses look their module up here
_spec.loader.exec_module(build)

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
]


def make_project(root: Path, claims: list[dict]) -> Path:
    (root / "claims").mkdir(parents=True)
    (root / "schemas").mkdir()
    shutil.copy(ROOT / "schemas" / "evidence-claim.v1.json", root / "schemas")
    for c in claims:
        (root / "claims" / f"{c['metadata']['name']}.yaml").write_text(yaml.safe_dump(c), encoding="utf-8")
    (root / "catalog.yaml").write_text(yaml.safe_dump_all(CATALOG), encoding="utf-8")
    cfg = root / "config.toml"
    cfg.write_text('repo = "Owner/Repo"\nsystem = "system:default/sys"\n[sources]\nclaims = ["claims"]\n'
                   'catalog = ["catalog.yaml"]\nschema = "schemas/evidence-claim.v1.json"\n'
                   '[labels]\nprioritise = ["research:prioritise"]\nreject = ["research:reject"]\n'
                   'dispute = ["research:question"]\nquestion = ["research:question"]\n', encoding="utf-8")
    return cfg


def all_html(out: Path) -> str:
    return "\n".join(p.read_text(encoding="utf-8") for p in sorted(out.rglob("*.html")))


class RealInput(unittest.TestCase):
    """The phase-0 claims in demos/research-loop, through site/config.toml."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "out"
        cls.site = build.build(ROOT / "site" / "config.toml", cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_claim_has_a_page_and_a_feed_entry(self):
        names = {c.name for c in self.site.claims}
        self.assertEqual(len(names), 25)
        self.assertEqual({p.stem for p in (self.out / "claims").glob("*.html")}, names)
        index = (self.out / "index.html").read_text(encoding="utf-8")
        self.assertEqual(set(re.findall(r'<li class="item" data-name="([^"]+)"', index)), names)
        for page in ("roles.html", "predictions.html", "how.html", "assets/style.css", "assets/app.js", ".nojekyll"):
            self.assertTrue((self.out / page).exists(), page)
        data = json.loads((self.out / "data" / "claims.json").read_text(encoding="utf-8"))
        self.assertEqual(len(data["claims"]), 25)

    def test_statuses_come_from_the_assessments(self):
        status = {c.name: c.status(self.site.system) for c in self.site.claims}
        self.assertEqual(status["gates-likelihood-readout-27-31b-matches-jev"], "did-not-transfer")
        self.assertEqual(status["gates-embedding-logreg-labelled"], "predicted")
        self.assertEqual(status["e04a-lfm3-pooled-accuracy"], "observation")
        roles = (self.out / "roles.html").read_text(encoding="utf-8")
        for role in ("decision-backend", "readout-calibration", "think-router"):
            self.assertIn(f'id="{role}"', roles)

    def test_no_outside_resources(self):
        text = all_html(self.out)
        self.assertNotRegex(text, r'<(script|link)[^>]+(src|href)="https?://')
        self.assertNotIn("<script>", text, "inline scripts would break the content security policy")
        self.assertNotIn(" style=", text)

    def test_issue_links_in_the_pages_are_well_formed(self):
        page = (self.out / "claims" / "gates-embedding-logreg-labelled.html").read_text(encoding="utf-8")
        links = [html.unescape(h) for h in re.findall(r'href="(https://github\.com/[^"]+/issues/new\?[^"]+)"', page)]
        self.assertEqual(len(links), 3)  # prioritise, reject, dispute (it has a prediction)
        for url in links:
            parts = urlsplit(url)
            self.assertEqual((parts.scheme, parts.netloc, parts.path), ("https", "github.com", "/OpenReplicant/Morphogen/issues/new"))
            q = parse_qs(parts.query, strict_parsing=True)
            self.assertEqual(set(q), {"title", "body", "labels"})
            self.assertIn("research-claim: gates-embedding-logreg-labelled", q["body"][0])
            self.assertTrue(q["labels"][0].startswith("research:"))
            self.assertLess(len(url), 8000)


class IssueUrl(unittest.TestCase):
    def test_round_trip(self):
        title, body = 'Prioritise: a & b? #1 "x"', "line one\nresearch-action: prioritise\n100% + more & <tags>"
        url = build.issue_url("OpenReplicant/Morphogen", title, body, ["research:prioritise", "two words"])
        parts = urlsplit(url)
        self.assertEqual(parts.netloc, "github.com")
        self.assertEqual(parts.path, "/OpenReplicant/Morphogen/issues/new")
        self.assertNotIn(" ", url)
        self.assertNotIn("\n", url)
        q = parse_qs(parts.query, strict_parsing=True)
        self.assertEqual(q["title"], [title])
        self.assertEqual(q["body"], [body])
        self.assertEqual(q["labels"], ["research:prioritise,two words"])

    def test_no_labels(self):
        q = parse_qs(urlsplit(build.issue_url("o/r", "t", "b", [])).query)
        self.assertNotIn("labels", q)


class UntrustedText(unittest.TestCase):
    """A claim's text comes from a paper: it must never become markup, and its links must never run script."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_text_from_files_is_escaped(self):
        cfg = make_project(self.root, [CLAIM])
        out = self.root / "out"
        build.build(cfg, out, root=self.root)
        text = all_html(out)
        self.assertNotIn("<script>alert", text)
        self.assertNotIn("<img src=x", text)
        self.assertNotIn("<b>beats</b>", text)
        self.assertIn("&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;", text)
        self.assertNotRegex(text, r'href="\s*javascript:', "a javascript: URL from a file was written as a link")
        page = (out / "claims" / "hostile-claim.html").read_text(encoding="utf-8")
        self.assertIn("A paper &lt;script&gt;", page)  # the title is still shown, as text
        # and paper text stays out of issue bodies (they render as Markdown)
        for href in re.findall(r'href="(https://github\.com/[^"]+)"', page):
            self.assertNotIn("alert", html.unescape(href))

    def test_safe_url(self):
        self.assertEqual(build.safe_url("https://arxiv.org/abs/1"), "https://arxiv.org/abs/1")
        for bad in ("javascript:alert(1)", " JaVaScRiPt:alert(1)", "data:text/html,x", "//evil", "", None, 3):
            self.assertIsNone(build.safe_url(bad), bad)

    def test_invalid_claim_stops_the_build(self):
        bad = copy.deepcopy(CLAIM)
        bad["spec"]["assessments"][0]["status"] = "probably-fine"
        cfg = make_project(self.root, [bad])
        with self.assertRaises(SystemExit) as ctx:
            build.build(cfg, self.root / "out", root=self.root)
        self.assertIn("not a valid EvidenceClaim", str(ctx.exception))


class AgentFiles(unittest.TestCase):
    """The research agent's own files (#110): the optional trial plan, queue.json, watch.yaml and seen.jsonl."""

    @unittest.skipUnless("TrialPlan" in (ROOT / "schemas" / "evidence-claim.v1.json").read_text(encoding="utf-8"),
                         "the schema has no assessments[].trial before #110")
    def test_queue_watch_and_trial_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claim = copy.deepcopy(CLAIM)
            claim["spec"]["assessments"][0]["trial"] = {"plan": "Run it " + HOSTILE, "cost_hours": 2.5,
                                                         "needs": ["data " + HOSTILE]}
            cfg = make_project(root, [claim])
            cfg.write_text(cfg.read_text(encoding="utf-8").replace('schema =', 'research = "research"\nschema ='),
                           encoding="utf-8")
            (root / "research").mkdir()
            (root / "research" / "queue.json").write_text(json.dumps({"date": "2026-11-27", "how": "bits / hours", "queue": [
                {"claim": "hostile-claim", "role": "component:default/role-x", "about": "component:default/opt-x",
                 "p_transfer": 0.4, "information_bits": 0.971, "cost_hours": 2.5, "score": 0.388,
                 "plan": "Run it " + HOSTILE, "reason": "R " + HOSTILE, "prioritised_by": ["someone"],
                 "rejected_by": [], "disputed_by": []}]}), encoding="utf-8")
            (root / "research" / "watch.yaml").write_text(yaml.safe_dump({"topics": [
                {"name": "topic-x", "question": "Q " + HOSTILE, "roles": ["role-x"], "terms": ["t1"]}]}), encoding="utf-8")
            (root / "research" / "seen.jsonl").write_text(json.dumps(
                {"id": "2611.00001", "title": "P " + HOSTILE, "status": "cataloged"}) + "\n", encoding="utf-8")
            out = root / "out"
            build.build(cfg, out, root=root)
            text = all_html(out)
            self.assertNotIn("<script>alert", text)
            queue = (out / "queue.html").read_text(encoding="utf-8")
            self.assertIn('href="claims/hostile-claim.html"', queue)
            self.assertIn("prioritised by someone", queue)
            self.assertIn("0.388", queue)
            claim_page = (out / "claims" / "hostile-claim.html").read_text(encoding="utf-8")
            self.assertIn("The cheapest trial that would settle it", claim_page)
            self.assertIn("about 2.5 hours", claim_page)
            self.assertIn("Number 1 of 1 in the", claim_page)
            roles = (out / "roles.html").read_text(encoding="utf-8")
            self.assertIn("topic-x", roles)
            self.assertIn("Papers seen", roles)

    def test_actions_the_agent_reads(self):
        """Every button's body names one of the agent's actions (morphogen/research.py, ACTIONS)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = make_project(root, [CLAIM])
            out = root / "out"
            build.build(cfg, out, root=root)
            actions = set()
            for href in re.findall(r'href="(https://github\.com/[^"]+/issues/new\?[^"]+)"', all_html(out)):
                body = parse_qs(urlsplit(html.unescape(href)).query)["body"][0]
                actions |= set(re.findall(r"^research-action: (\S+)$", body, re.M))
            self.assertEqual(actions, {"prioritise", "reject", "dispute", "question", "propose-role", "propose-option"})


class Calibration(unittest.TestCase):
    def test_scored_prediction_shows_on_the_chart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            scored = copy.deepcopy(CLAIM)
            scored["metadata"]["name"] = "scored-claim"
            scored["spec"]["source"]["url"] = "https://arxiv.org/abs/2611.00001"
            a = scored["spec"]["assessments"][0]
            a["status"] = "did-not-transfer"
            a["outcome"] = {"trial": {"id": "T-1"}, "observed": ["hostile-claim"], "summary": "Lower.",
                            "comparison": "our-setup", "verdict": {"by": "morphogen", "decision": "refuse"}}
            cfg = make_project(root, [CLAIM, scored])
            site = build.build(cfg, root / "out", root=root)
            self.assertEqual([(p, o) for p, o, _ in build.calibration_pairs(site)], [(0.4, 0)])
            self.assertAlmostEqual(build.brier(build.calibration_pairs(site)), 0.16)
            page = (root / "out" / "predictions.html").read_text(encoding="utf-8")
            self.assertIn("Brier score <strong class='mono'>0.160</strong>", page)
            self.assertIn('<g class="dot">', page)


if __name__ == "__main__":
    unittest.main()
