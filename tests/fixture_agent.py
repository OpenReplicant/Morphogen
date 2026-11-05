"""A sample agent-like target measured by OpenTelemetry."""

from tests.fixture import Project


# --- an agent-like target measured by OpenTelemetry: the harness reports cost and requests over
# OTLP/HTTP JSON, as Claude Code does with CLAUDE_CODE_ENABLE_TELEMETRY=1, honouring the same
# exporter variables. The candidate's agent.py decides how many steps (model calls) it takes.

AGENT = '''"""The agent's plan. STEPS model calls; fewer is cheaper."""
STEPS = 10


def plan():
    return STEPS
'''

AGENT_BENCH = '''"""The workload: run the agent, and report its usage over OTLP/HTTP JSON (part of the harness)."""
import json, os, urllib.request
from agent import plan


def attrs(d):
    return [{"key": k, "value": {"stringValue": str(v)}} for k, v in d.items()]


steps = plan()
print(steps)
if os.environ.get("CLAUDE_CODE_ENABLE_TELEMETRY") == "1":
    res = {"resource": {"attributes": attrs(dict(kv.split("=", 1) for kv in
                                                 os.environ.get("OTEL_RESOURCE_ATTRIBUTES", "").split(",") if kv))}}
    end = os.environ["OTEL_EXPORTER_OTLP_ENDPOINT"]

    def post(path, body):
        urllib.request.urlopen(urllib.request.Request(end + path, json.dumps(body).encode(),
                                                      {"Content-Type": "application/json"}), timeout=5).read()

    if os.environ.get("OTEL_METRICS_EXPORTER", "none") != "none":
        points = [{"asDouble": 0.01, "attributes": attrs({"model": "m"})} for _ in range(steps)]
        tokens = [{"asInt": "100", "attributes": attrs({"type": "output"})} for _ in range(steps)]
        post("/v1/metrics", {"resourceMetrics": [{**res, "scopeMetrics": [{"metrics": [
            {"name": "claude_code.cost.usage", "unit": "USD",
             "sum": {"dataPoints": points, "aggregationTemporality": 1, "isMonotonic": True}},
            {"name": "claude_code.token.usage", "unit": "tokens",
             "sum": {"dataPoints": tokens, "aggregationTemporality": 1, "isMonotonic": True}}]}]}]})
    if os.environ.get("OTEL_LOGS_EXPORTER", "none") != "none":
        recs = [{"body": {"stringValue": "claude_code.api_request"},
                 "attributes": attrs({"event.name": "api_request", "duration_ms": 120})} for _ in range(steps)]
        post("/v1/logs", {"resourceLogs": [{**res, "scopeLogs": [{"logRecords": recs}]}]})
'''

AGENT_TARGET = '''name: agent
harness: [bench.py]
measure:
  run: python bench.py
  warmup: 0
  repeats: 4
  max_repeats: 8
  same_output: false
  observer:
    type: otel
    collected: outside
    settle_ms: 150
    metrics:
      cost_usd: {metric: claude_code.cost.usage}
      output_tokens: {metric: claude_code.token.usage, where: {type: output}}
      api_requests: {event: claude_code.api_request, count: true}
      api_ms: {event: claude_code.api_request, field: duration_ms}
  metrics:
    observed.cost_usd: {direction: lower, primary: true, min_improvement: 0.10}
timeout: 60
parameters:
  steps: {file: agent.py, name: STEPS, owner: agent, range: [1, 20]}
'''


class AgentProject(Project):
    target = "targets/agent"

    def __init__(self):
        super().__init__({"agent.py": AGENT, "bench.py": AGENT_BENCH, "target.yaml": AGENT_TARGET}, sample=None)
