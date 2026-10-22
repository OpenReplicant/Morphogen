# 0004 cognee as the knowledge provider, two kinds of dataset

Status: accepted, pending spike · 2026-10-22

**Decision.** cognee is the knowledge provider, behind a thin domain layer (`src/morphogen/domain/`). Ingestors use the SDK and end in `add_data_points`. Two kinds of dataset:

- `map`: written only by ingestors.
- `agent-memory-<agent>`: written by that agent's harness (cognee-memory plugin for Claude Code, `remember` over MCP elsewhere).

**Why.** Use cognee's extension points (DataPoints, Tasks, Pipelines, adapters) instead of maintaining a parallel store. The dataset split lets agents keep working memory without breaking the single-writer rule.

**Risk.** cognee is built for memory extraction; couplings-as-nodes, bitemporality, retraction, changed-ID reporting and access control must pass the spike (`docs/spike-cognee.md`). If not, claims move to our own Postgres tables and cognee keeps extraction and search.
