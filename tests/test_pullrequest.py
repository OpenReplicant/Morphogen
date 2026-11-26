"""A pull request as the GitHub judge sees it (morphogen/pullrequest.py, `morphogen pr`, .github/workflows/judge.yml):
not judged, refused, or handed to the judge as a request. The cheats a pull request could try through this path are in
PullRequestCheats; each must be refused. WorkflowFile holds the workflow to what the old one guaranteed."""

import argparse
import contextlib
import io
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from morphogen import pullrequest as pr
from morphogen import schema
from morphogen.documents import DocumentError
from tests.catalog import FILE, dump
from tests.fixture import CLASSIFY, git
from tests.fixture_cells import CellsProject, cells_doc

ROOT = Path(__file__).resolve().parents[1]
HONEST = CLASSIFY + "LIMIT = 100\n# same\n"
BETTER = CLASSIFY.replace("THRESHOLD = 10", "THRESHOLD = 50")


def rev(repo, ref):
    return subprocess.run(["git", "rev-parse", ref], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


class PullRequests(unittest.TestCase):
    def setUp(self):
        self.p = CellsProject(code=True)
        self.p.write("README.md", "the app\n")
        git(self.p.repo, "add", "README.md")
        git(self.p.repo, "commit", "-q", "-m", "readme")
        # The operator's private material, as the workflow clones it: outside the repository, paths relative to it.
        self.cases = Path(tempfile.mkdtemp(prefix="morphogen-cases-"))
        shutil.copytree(self.p.private_dir, self.cases / "answers")
        (self.cases / "morphogen.local.yaml").write_text(yaml.safe_dump({"cells": {"classify": {"private": "answers"}}}))

    def tearDown(self):
        self.p.close()
        shutil.rmtree(self.cases, ignore_errors=True)

    def judge(self, head, **kw):
        kw.setdefault("local_file", self.cases / "morphogen.local.yaml")
        kw.setdefault("protect", [".github/**"])
        return pr.judge_pr(self.p.repo, "main", head, sandbox="none", unsandboxed=True, **kw)

    def records(self):
        return self.p.evidence.dump()


class PullRequestRuns(PullRequests):
    def test_a_change_no_cell_claims_is_not_judged(self):
        r = self.judge(self.p.branch("docs", {"README.md": "more\n"}))
        self.assertEqual(r["verdict"], "not-judged", r)
        self.assertFalse(r["judged"])
        self.assertEqual(self.records(), [])

    def test_a_change_with_no_target_is_judged_as_a_change(self):
        r = self.judge(self.p.branch("honest", {"classify/classify.py": HONEST}))
        self.assertEqual((r["verdict"], r["kind"]), ("pass", "change"), r)
        rec = r["evidence"]
        self.assertEqual(rec, self.records()[-1])
        self.assertEqual(rec["request"]["kind"], "change")
        schema.Verdict.model_validate(rec)

    def test_the_description_names_the_target_and_the_answers_come_from_the_local_file(self):
        body = "Raise the threshold.\n\nmorphogen-target: cell:classify\n"
        r = self.judge(self.p.branch("same", {"classify/classify.py": HONEST}), body=body,
                       labels={"pull_request": "7"})
        self.assertEqual((r["kind"], r["target"]), ("judge", "cell:classify"), r)
        self.assertEqual(r["verdict"], "fail", r)              # identical behaviour is no gain
        self.assertIn("scored.accuracy", r["result"]["metrics"])   # the scorer read the answers the local file names
        rec = self.records()[-1]
        self.assertEqual(rec["request"]["kind"], "judge")
        self.assertEqual(rec["labels"], {"pull_request": "7"})
        schema.Verdict.model_validate(rec)

    def test_a_better_candidate_passes_on_the_held_out_answers(self):
        better = BETTER + "LIMIT = 100\n"
        r = self.judge(self.p.branch("t50", {"classify/classify.py": better}), body="morphogen-target: cell:classify")
        self.assertEqual(r["verdict"], "pass", r)
        self.assertEqual(r["summary"], "pass cell:classify")

    def test_a_branch_behind_the_base_is_judged_merged_onto_it_by_the_current_rules(self):
        head = rev(self.p.repo, self.p.branch("honest", {"classify/classify.py": HONEST}))
        self.p.write("README.md", "main moved on\n")
        git(self.p.repo, "commit", "-q", "-am", "main moves")
        r = self.judge(head)
        self.assertTrue(r["merged"], r)
        self.assertEqual(r["head"], head)
        self.assertNotEqual(r["candidate"], head)
        self.assertEqual(r["verdict"], "pass", r)   # README.md, changed only on main, is not the candidate's

    def test_a_branch_that_does_not_merge_is_a_stop(self):
        head = self.p.branch("readme", {"README.md": "theirs\n"})
        self.p.write("README.md", "ours\n")
        git(self.p.repo, "commit", "-q", "-am", "main moves")
        with self.assertRaises(pr.PullRequestError) as e:
            self.judge(head)
        self.assertIn("does not merge", str(e.exception))

    def test_the_command_writes_the_document_and_exits_by_the_verdict(self):
        head = self.p.branch("honest", {"classify/classify.py": HONEST})
        out = self.cases.parent / f"{self.cases.name}-verdict.json"
        self.addCleanup(lambda: out.unlink(missing_ok=True))
        a = argparse.Namespace(base="main", head=head, sandbox="none", unsandboxed=True, pull=False, target=None,
                               body_env=None, protect=None, label=["k=v"], out=str(out),
                               local=str(self.cases / "morphogen.local.yaml"))
        import os
        cwd = os.getcwd()
        os.chdir(self.p.repo)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pr.main(a), 0)
            doc = json.loads(out.read_text())
            self.assertEqual((doc["morphogen"], doc["verdict"]), ("pr-verdict/v1", "pass"))
            self.assertLessEqual(len(doc["summary"]), 138)
            a.sandbox, a.unsandboxed = "none", False
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(pr.main(a), 2)
            self.assertEqual(json.loads(out.read_text())["verdict"], "stop")
        finally:
            os.chdir(cwd)


class PullRequestCheats(PullRequests):
    def assertRefused(self, r, why):
        self.assertEqual(r["verdict"], "fail", r)
        self.assertTrue(r["judged"])
        self.assertIn(why, " ".join(r["reasons"]))

    def widened(self):
        d = cells_doc(code=True)
        d["cells"]["classify"]["change"] = "**"
        return dump(d)

    def test_widen_change_in_the_catalog(self):
        r = self.judge(self.p.branch("widen", {FILE: self.widened(), "classify/classify.py": HONEST}))
        self.assertRefused(r, FILE)
        self.assertEqual(r["kind"], "change")
        self.assertEqual(self.records()[-1]["verdict"], "fail")

    def test_widen_change_in_the_catalog_while_naming_the_target(self):
        r = self.judge(self.p.branch("widen", {FILE: self.widened(), "classify/classify.py": HONEST}),
                       body="morphogen-target: cell:classify")
        self.assertRefused(r, FILE)
        self.assertEqual(r["kind"], "judge")
        self.assertEqual(r["result"]["metrics"], {})   # refused before anything ran

    def test_edit_only_the_catalog_to_slip_by_as_not_judged(self):
        r = self.judge(self.p.branch("widen", {FILE: self.widened()}))
        self.assertRefused(r, FILE)

    def test_delete_the_catalog(self):
        r = self.judge(self.p.branch("gone", delete=[FILE]))
        self.assertRefused(r, FILE)

    def test_commit_a_local_file_with_wider_answers(self):
        repo, mine = self.p.repo, (self.p.repo / "morphogen.local.yaml").read_text()
        git(repo, "checkout", "-q", "-B", "local", "main")
        (repo / "morphogen.local.yaml").write_text("cells: {classify: {private: /tmp}}\n")
        git(repo, "add", "-f", "morphogen.local.yaml")
        git(repo, "commit", "-q", "-m", "local")
        git(repo, "checkout", "-q", "main")
        (repo / "morphogen.local.yaml").write_text(mine)
        r = self.judge("local")
        self.assertRefused(r, "morphogen.local.yaml")

    def test_edit_the_callers_workflow(self):
        r = self.judge(self.p.branch("wf", {".github/workflows/morphogen.yml": "on: push\n"}))
        self.assertRefused(r, "protected")
        rec = self.records()[-1]
        self.assertEqual((rec["verdict"], rec["by"]), ("fail", "judge"))
        schema.Verdict.model_validate(rec)

    def test_carry_rules_in_the_local_file(self):
        (self.cases / "morphogen.local.yaml").write_text(yaml.safe_dump({"cells": {"classify": {"change": "**"}}}))
        with self.assertRaises(DocumentError) as e:
            self.judge(self.p.branch("honest", {"classify/classify.py": HONEST}))
        self.assertIn("not a local setting", str(e.exception))

    def test_run_without_a_container(self):
        with self.assertRaises(pr.PullRequestError) as e:
            pr.judge_pr(self.p.repo, "main", self.p.branch("honest", {"classify/classify.py": HONEST}), sandbox="none")
        self.assertIn("held-out answers", str(e.exception))

    def test_name_two_targets(self):
        with self.assertRaises(pr.PullRequestError):
            pr.target_from("morphogen-target: cell:classify\nmorphogen-target: cell:report\n")

    def test_add_the_first_catalog_through_the_judge(self):
        git(self.p.repo, "rm", "-q", FILE)
        git(self.p.repo, "commit", "-q", "-m", "no catalog")
        r = self.judge(self.p.branch("first", {FILE: dump(cells_doc(code=True))}))
        self.assertRefused(r, "by review")


class WorkflowFile(unittest.TestCase):
    """.github/workflows/judge.yml keeps what the old judge (rebuild 8, b921c9b) guaranteed."""

    def setUp(self):
        self.text = (ROOT / ".github/workflows/judge.yml").read_text()
        self.wf = yaml.safe_load(self.text)

    def test_it_is_reusable_and_judges_only_pull_request_target(self):
        self.assertIn("workflow_call", self.wf[True])   # YAML 1.1 reads the key `on` as True
        for name, job in self.wf["jobs"].items():
            self.assertIn("pull_request_target", job["if"], name)

    def test_no_job_has_more_than_it_needs(self):
        self.assertEqual(self.wf["permissions"], {})
        self.assertEqual(self.wf["jobs"]["judge"]["permissions"], {"contents": "read"})   # the job that runs candidates
        self.assertEqual(set(self.wf["jobs"]["post"]["permissions"]), {"statuses", "id-token"})

    def test_actions_are_pinned_by_commit(self):
        uses = [s["uses"] for job in self.wf["jobs"].values() for s in job["steps"] if "uses" in s]
        self.assertTrue(uses)
        for u in uses:
            self.assertRegex(u, r"@[0-9a-f]{40}\Z", u)

    def test_the_description_never_reaches_a_shell_script(self):
        for job in self.wf["jobs"].values():
            for step in job["steps"]:
                self.assertNotIn("github.event.pull_request.body", step.get("run", ""))
                self.assertNotIn("github.event.pull_request.title", step.get("run", ""))

    def test_the_judge_is_the_packages_and_never_unsandboxed(self):
        steps = {s.get("id"): s for s in self.wf["jobs"]["judge"]["steps"]}
        run = steps["judge"]["run"]
        self.assertIn("-P -m morphogen pr", run)
        self.assertNotIn("--unsandboxed", self.text)
        check = self.wf["jobs"]["judge"]["steps"][0]["run"]
        self.assertIn("docker|podman", check)

    def test_the_private_material_is_removed(self):
        names = [s.get("name", "") for s in self.wf["jobs"]["judge"]["steps"]]
        i = names.index("Remove the private material")
        self.assertEqual(self.wf["jobs"]["judge"]["steps"][i]["if"], "always()")

    def test_the_lock_is_uv_lock(self):
        uv = shutil.which("uv")
        if not uv:
            self.skipTest("uv is not installed")
        r = subprocess.run([uv, "export", "--frozen", "--no-dev", "--no-emit-project", "--format", "requirements-txt"],
                           cwd=ROOT, capture_output=True, text=True)
        if r.returncode != 0:
            self.skipTest(f"uv export: {r.stderr.strip()[-200:]}")

        def reqs(text):
            return [line for line in text.splitlines() if line.strip() and not line.startswith("#")]
        self.assertEqual(reqs((ROOT / "requirements.lock").read_text()), reqs(r.stdout),
                         "regenerate: uv export --frozen --no-dev --no-emit-project --format requirements-txt "
                         "-o requirements.lock")


if __name__ == "__main__":
    unittest.main()
