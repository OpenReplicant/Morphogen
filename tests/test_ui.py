"""The web UI: its JSON API on a project with evidence, the page, and that it only reads."""

import copy
import json
import threading
import unittest
import urllib.error
import urllib.request


from morphogen import judge as judge_mod
from morphogen.ui import PAGE, Api, serve
from tests.fixture import CLASSIFY, CLASSIFY_CELL, ScoredProject


class Ui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p = ScoredProject(
            cells={"app": {"provides": "labels"},
                   "classify": {"in": "app", "provides": "score", **copy.deepcopy(CLASSIFY_CELL)},
                   "report": {"in": "app", "consumes": "score"}},
            interfaces={"labels": {"tests": "cd targets/classify && python -m unittest -q test_classify",
                                   "external": "consumes"},
                        "score": []})
        judge_mod.measure(cls.p.repo, cls.p.cfg, cls.p.target, "main", cls.p.evidence)
        cls.p.judge(cls.p.branch("t50", {"classify.py": CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 50")}))
        cls.httpd = serve(cls.p.repo, "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.p.close()

    def get(self, path):
        with urllib.request.urlopen(self.base + path) as r:
            return r.status, r.headers.get("Content-Type"), r.read()

    def test_the_page_pins_its_libraries(self):
        status, ctype, body = self.get("/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ctype)
        html = body.decode()
        self.assertIn('x-data="app()"', html)
        self.assertRegex(html, r"alpinejs@\d+\.\d+\.\d+/")
        self.assertRegex(html, r"mermaid@\d+\.\d+\.\d+/")
        self.assertEqual(body, PAGE.read_bytes())

    def test_overview_structure_scope(self):
        o = json.loads(self.get("/api/overview")[2])
        self.assertEqual(o["evidence"]["chain"], "intact")
        self.assertEqual(o["evidence"]["kinds"], {"measurement": 1, "verdict": 1})
        s = json.loads(self.get("/api/structure")[2])
        self.assertEqual(s["roots"], ["app"])
        self.assertEqual(s["cells"]["app"]["children"], ["classify", "report"])
        self.assertIn("flowchart LR", s["mermaid"])
        self.assertEqual(s["coverage"]["tested"], 1)
        sc = json.loads(self.get("/api/scope?cell=classify")[2])
        self.assertEqual(sc["neighbours"], ["report"])

    def test_evidence_filters(self):
        ev = json.loads(self.get("/api/evidence?kind=verdict")[2])
        self.assertEqual([r["verdict"] for r in ev], ["pass"])
        self.assertEqual(ev[0]["outcome"]["metrics"]["scored.accuracy"]["gain_kind"], "absolute")
        self.assertEqual(json.loads(self.get("/api/evidence?by=agent")[2]), [])
        self.assertEqual(len(json.loads(self.get("/api/evidence?contains=measures")[2])), 1)

    def test_targets(self):
        t = json.loads(self.get("/api/targets")[2])
        self.assertEqual([x["path"] for x in t], ["cell:classify"])
        self.assertEqual(t[0]["change"], ["targets/classify/classify.py"])
        self.assertEqual(t[0]["primary"], "scored.accuracy")
        self.assertEqual(t[0]["verdicts"], {"pass": 1, "fail": 0})
        self.assertIsNotNone(t[0]["last_measurement"])

    def test_errors_and_files_outside_the_project(self):
        for path in ("/api/scope?cell=nope", "/api/structure?file=../../etc/passwd", "/api/nothing"):
            with self.assertRaises(urllib.error.HTTPError) as e:
                self.get(path)
            self.assertIn(e.exception.code, (400, 404))

    def test_it_only_reads(self):
        before = len(self.p.evidence.dump())
        for path in ("/api/overview", "/api/structure", "/api/evidence", "/api/targets"):
            self.get(path)
        self.assertEqual(len(self.p.evidence.dump()), before)
        req = urllib.request.Request(self.base + "/api/overview", data=b"{}", method="POST")
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req)
        self.assertEqual(e.exception.code, 501)

    def test_api_without_http(self):
        self.assertEqual(Api(self.p.repo).structure("missing.yaml")["missing"], True)


if __name__ == "__main__":
    unittest.main()
