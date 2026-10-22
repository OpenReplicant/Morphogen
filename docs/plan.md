# Plan

## Week 1: spikes (decide before building on them)

See `spike-cognee.md`. Exit: a short written result per spike and any superseding decision records.

## Milestone 1: the system designs and maps itself

Thinnest slice, in order. Each step ends with a runnable check.

| # | Build | Acceptance check |
| --- | --- | --- |
| 1 | Local stack: Postgres (pgvector, AGE), OTel Collector, Caddy, cognee | `docker compose up` healthy; `scripts/smoke.sh` passes |
| 2 | Ontology DataPoints + claim fields (status, level, valid/record time, provenance, confidence, environment) | Unit tests create, close and query a claim at two valid times |
| 3 | Intake: CloudEvents endpoint validating against `schemas/events/` | Invalid event → 400; valid event → 202 and archived |
| 4 | Blueprint ingestor: `blueprint.submitted` → hypothetical slots/couplings | Submitting `examples/self-blueprint.json` yields the expected slots and couplings |
| 5 | Completion events from every pipeline run | Event lists created IDs matching the graph |
| 6 | Map MCP server: `status`, `slots`, `couplings`, `drift`, `propose` | Claude Code with the `morphogen` plugin can list the blueprint and send a valid proposal |
| 7 | Trace ingestor: spans → observed slots and couplings | Running the stack produces observed couplings intake→ingestor→postgres |
| 8 | Drift query + sweep watcher | Drift lists blueprint couplings not yet observed; clears when traced |
| 9 | UI shell + graph explorer view | Explorer shows hypothetical vs observed, filterable |
| 10 | Intent path: promoter commits a new provider to `intent/environments/sandbox/` | New service appears in the map only after its traces arrive |

Done when step 10 passes and map-quality metrics (coverage, freshness, precision, drift) are reported for the self-map.

## Milestone 2 (sketch)

Catalog resolution over configured registries (container registry, PyPI, MCP registry, private registries), review queue view, governance policies enforced by the promoter, first experiment with a control.

## Out of scope for now

Embodied fast loop, open web catalog discovery, multiple targets, product layer.
