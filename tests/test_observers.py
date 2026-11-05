"""The observer slot: the OTLP receiver, the otel observer through the judge and tune, and its refusals."""

import json
import os
import unittest
import urllib.request

from morphogen import judge as judge_mod
from morphogen import observers
from morphogen.optimize import make, tune
from tests.fixture import AGENT, AgentProject


def post(path, body):
    r = observers.receiver()
    urllib.request.urlopen(urllib.request.Request(r.endpoint + path, json.dumps(body).encode(),
                                                  {"Content-Type": "application/json"}), timeout=5).read()


def res(run):
    return {"resource": {"attributes": [{"key": "morphogen.run_id", "value": {"stringValue": run}}]}}


class Receiver(unittest.TestCase):
    def collect(self, run, metrics):
        return observers.OtelObserver({"metrics": metrics, "settle_ms": 0}).collect(run)

    def test_sums_by_run_with_filters_and_events(self):
        post("/v1/metrics", {"resourceMetrics": [{**res("r1"), "scopeMetrics": [{"metrics": [
            {"name": "claude_code.token.usage", "sum": {"aggregationTemporality": 1, "dataPoints": [
                {"asInt": "10", "attributes": [{"key": "type", "value": {"stringValue": "input"}}]},
                {"asInt": "7", "attributes": [{"key": "type", "value": {"stringValue": "output"}}]},
                {"asInt": "5", "attributes": [{"key": "type", "value": {"stringValue": "output"}}]}]}}]}]},
            {**res("other"), "scopeMetrics": [{"metrics": [
                {"name": "claude_code.token.usage", "sum": {"dataPoints": [{"asInt": "999"}]}}]}]}]})
        post("/v1/logs", {"resourceLogs": [{**res("r1"), "scopeLogs": [{"logRecords": [
            {"body": {"stringValue": "claude_code.tool_result"},
             "attributes": [{"key": "success", "value": {"stringValue": "false"}}]},
            {"attributes": [{"key": "event.name", "value": {"stringValue": "tool_result"}},
                            {"key": "success", "value": {"stringValue": "true"}}]}]}]}]})
        out = self.collect("r1", {"out": {"metric": "claude_code.token.usage", "where": {"type": "output"}},
                                  "all": {"metric": "claude_code.token.usage"},
                                  "failures": {"event": "claude_code.tool_result", "where": {"success": "false"},
                                               "count": True},
                                  "results": {"event": "claude_code.tool_result", "count": True}})
        self.assertEqual(out, {"out": 12.0, "all": 22.0, "failures": 1.0, "results": 2.0})

    def test_cumulative_takes_the_last_total(self):
        post("/v1/metrics", {"resourceMetrics": [{**res("r2"), "scopeMetrics": [{"metrics": [
            {"name": "c", "sum": {"aggregationTemporality": 2, "dataPoints": [{"asDouble": 1.0}, {"asDouble": 3.0}]}}]}]}]})
        self.assertEqual(self.collect("r2", {"c": {"metric": "c"}}), {"c": 3.0})

    def test_silence_and_negative_sums_are_the_candidates_fault(self):
        with self.assertRaises(observers.ObserverError) as e:
            self.collect("never", {"c": {"metric": "c"}})
        self.assertEqual(e.exception.fault, "candidate")
        post("/v1/metrics", {"resourceMetrics": [{**res("r3"), "scopeMetrics": [{"metrics": [
            {"name": "c", "sum": {"dataPoints": [{"asDouble": -1.0}]}}]}]}]})
        with self.assertRaises(observers.ObserverError) as e:
            self.collect("r3", {"c": {"metric": "c"}})
        self.assertEqual(e.exception.fault, "candidate")

    def test_the_run_is_pointed_at_the_receiver(self):
        env = observers.OtelObserver({"metrics": {"c": {"metric": "c"}}}).env("x")
        self.assertEqual(env["CLAUDE_CODE_ENABLE_TELEMETRY"], "1")
        self.assertEqual(env["OTEL_EXPORTER_OTLP_PROTOCOL"], "http/json")
        self.assertEqual(env["OTEL_EXPORTER_OTLP_ENDPOINT"], observers.receiver().endpoint)
        self.assertTrue(env["OTEL_EXPORTER_OTLP_ENDPOINT"].startswith("http://127.0.0.1:"))


class OtelThroughTheJudge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if os.environ.get("MORPHOGEN_TEST_SANDBOX", "none") != "none":
            raise unittest.SkipTest("the otel observer runs with sandbox: none (containers have no network)")
        cls.p = AgentProject()

    @classmethod
    def tearDownClass(cls):
        cls.p.close()

    def test_fewer_steps_cost_less_and_pass(self):
        r = self.p.judge(self.p.branch("five", {"agent.py": AGENT.replace("STEPS = 10", "STEPS = 5")}))
        self.assertEqual(r["verdict"], "pass", r)
        m = r["metrics"]["observed.cost_usd"]
        self.assertAlmostEqual(m["base"], 0.10, places=6)
        self.assertAlmostEqual(m["candidate"], 0.05, places=6)
        rec = self.p.evidence.query(by="judge", where={"kind": "verdict"}, limit=1)[0]
        self.assertEqual(rec["outcome"]["metrics"]["observed.cost_usd"]["candidate"], m["candidate"])

    def test_measure_reports_every_observed_metric(self):
        r = judge_mod.measure(self.p.repo, self.p.cfg, self.p.target, "main", self.p.evidence)
        self.assertEqual(r["metrics"]["observed.api_requests"], 10.0)
        self.assertEqual(r["metrics"]["observed.output_tokens"], 1000.0)
        self.assertEqual(r["metrics"]["observed.api_ms"], 1200.0)

    def test_tune_lowers_cost_through_telemetry(self):
        r = tune(self.p.repo, self.p.cfg, self.p.target, make("hillclimb", trials=12), self.p.evidence,
                 rounds=1, max_trials=12)
        self.assertEqual(r["verdict"], "pass", r.get("note"))
        self.assertLess(r["best"]["values"]["agent.STEPS"], 10)

    def test_a_container_runner_is_refused(self):
        from unittest import mock
        spec = judge_mod.structure_of(self.p.repo).spec("agent")
        with mock.patch.object(judge_mod, "capabilities", return_value={"network_isolated": True}), \
                mock.patch.object(judge_mod, "sandbox_mode", return_value="podman"):
            with self.assertRaises(judge_mod.JudgeError) as e:
                judge_mod._check_runner(spec, {"sandbox": "podman"})
        self.assertIn("network", str(e.exception))

if __name__ == "__main__":
    unittest.main()
