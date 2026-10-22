# Plan

## Week 1: spikes (decide before building on them)

See `spike-cognee.md`. Exit: a short written result per spike and any superseding decision records. Results: `spike-results.md`, decision 0011.

## Milestone 1: the system designs and maps itself

Thinnest slice, in order. Each step ends with a runnable check.

| # | Build | Acceptance check | Status |
| --- | --- | --- | --- |
| 1 | Local stack: Postgres (pgvector, AGE), OTel Collector, Caddy | `docker compose up` healthy; `scripts/smoke.sh` passes | Written, not yet run with Docker |
| 2 | Ontology + claim fields (status, level, valid/record time, provenance, confidence, environment) | Unit tests create, close and query a claim at two valid times | Done: `tests/test_claims.py` |
| 3 | Intake: CloudEvents endpoint validating against `schemas/events/` | Invalid event → 400; valid event → 202 and archived | Done: `tests/test_intake.py` |
| 4 | Blueprint ingestor: `blueprint.submitted` → hypothetical slots/couplings | Submitting `examples/self-blueprint.json` yields the expected slots and couplings | Done: `tests/test_blueprint.py` |
| 5 | Completion events from every pipeline run | Event lists created IDs matching the graph | Done: `tests/test_blueprint.py` |
| 6 | Map MCP server: `status`, `slots`, `couplings`, `drift`, `propose` | Claude Code with the `morphogen` plugin can list the blueprint and send a valid proposal | Done: `tests/test_mcp.py`; live over stdio |
| 7 | Trace ingestor: spans → observed slots and couplings | Running the stack produces observed couplings intake→ingestor→postgres | Done: `tests/test_traces_and_drift.py`; live without Collector |
| 8 | Drift query + sweep watcher | Drift lists blueprint couplings not yet observed; clears when traced | Done |
| 9 | UI shell + graph explorer view | Explorer shows hypothetical vs observed, filterable | Done: `ui/views/graph-explorer.html` |
| 10 | Intent path: promoter commits a new provider to `intent/environments/sandbox/` | New service appears in the map only after its traces arrive | Done: `tests/test_promoter.py`; live |

Done when step 10 passes and map-quality metrics (coverage, freshness, precision, drift) are reported for the self-map (`uv run morphogen-report`).

Open for Milestone 1: run step 1 under Docker (Collector → intake coupling `c1` is the only drift left in the live run, see `spike-results.md`); orchestrator adapter (Docker Compose) reconciling `intent/environments/sandbox/`.

## Milestone 2 (sketch)

Catalog resolution over configured registries (container registry, PyPI, MCP registry, private registries), review queue view, governance policies enforced by the promoter, first experiment with a control.

## Out of scope for now

Embodied fast loop, open web catalog discovery, multiple targets, product layer.
