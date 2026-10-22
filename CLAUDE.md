# Morphogen

Morphogen (OpenReplicant) is a system that maps any system as **slots and couplings**, holds what it knows in one knowledge store (bitemporal claims in Postgres), and adapts what it maps through a **MAPE-K loop** whose changes are tested as hypotheses before promotion. It starts by designing and mapping itself.

Full architecture: @docs/architecture.md
Plan and acceptance tests: @docs/plan.md
Agent rules (any harness): @AGENTS.md

## Invariants (never break these; flag any change that would)

1. **Only ingestors write the map.** Every other write (belief updates, promotions, retractions, catalog notes) is an event that an ingestor writes.
2. **Only orchestrators touch the world.** Change happens by committing declarative files to `intent/`; orchestrators reconcile them.
3. **Only review turns a proposal into intent.** The promoter applies policy (`intent/policies/`) and routes to a human when required.
4. **Every observation enters through a declared intake**: OTLP (OTel Collector) or CloudEvents over HTTP.
5. **Every coupling has a contract**; transport is optional detail (a realization).
6. **Every slot in this architecture has a default provider and a swappable interface.** Defaults are choices, not dependencies.
7. **The map is not the territory.** The graph never drives actuation.

## Vocabulary

| Term | Meaning |
| --- | --- |
| Slot | A role in a context: typed hole with interface, cardinality, scope. Not necessarily a container |
| Provider | What fills a slot; may itself be a slot graph |
| Port | Named input/output on a slot, with a payload type |
| Coupling | A **node** joining ports; has type, contract, observations, history |
| Requirement / Capability | What a slot needs / what a provider offers; matching generates candidates |
| Realization | Optional slot graph of how a coupling is transported |
| Claim status | observed / intended / hypothetical |
| Claim level | instance / type (catalog entries are type-level) |
| Valid time / record time | When true in the world / when the system learned it (bitemporal) |
| Completion event | Published after every ingest pipeline run, with IDs created/changed/retired |

## Stack (decided)

Python 3.12 + uv · map store: bitemporal claim tables in Postgres behind `MapStore` (decision 0011) · Postgres 16 with pgvector + Apache AGE · cognee optional (`--extra cognee`, search/extraction later) · MCP Python SDK 2.x · OTel Collector · Caddy · Alpine.js + daisyUI shell · PostgREST (read-only role) · Docker Compose for local. License: Apache-2.0.

Decision records live in `docs/decisions/`. Do not reopen a decided record without writing a new one that supersedes it.

## Map and agent memory

- The map (`map.claims`, read views in `api.*`): written **only** by ingestors, as the `morphogen_ingestor` role. Watchers, the promoter and the MCP server read it as `morphogen_reader`.
- `agent-memory-*`: per agent or harness, written by the harness (cognee-memory plugin or `remember`). Agents read the map, never write it.

## Code map

| Path | Slot |
| --- | --- |
| `src/morphogen/intake/` | CloudEvents + OTLP endpoints, router (fan-out), raw archive |
| `src/morphogen/ingest/` | Ingestors: blueprint, traces, proposals, intent (the only map writers) |
| `src/morphogen/store/` | `MapStore` interface; Postgres and memory providers; `schema.sql` |
| `src/morphogen/queries.py` | Read-only: drift, blast radius, map-quality metrics |
| `src/morphogen/watchers/` | Drift watcher (event-driven + sweep); emits findings |
| `src/morphogen/promoter/` | Policy × risk, guards, governance state, writes and commits `intent/` |
| `src/morphogen/orchestrators/` | Orchestrator adapters (Docker Compose): reconcile `intent/environments/<env>/` |
| `src/morphogen/mcp/server.py` | `morphogen-map` MCP server |
| `src/morphogen/telemetry.py` | Spans carry `morphogen.slot` / `morphogen.peer.slot` so the system maps itself |

## Commands

```
uv sync                         # install
docker compose -f deploy/docker-compose.yml up -d
scripts/smoke.sh                # milestone 1 smoke test against the stack
uv run pytest                   # tests (memory store)
MORPHOGEN_TEST_DATABASE_URL=postgresql://... uv run pytest   # also against Postgres
uv run ruff check src tests     # lint
uv run morphogen-report         # map quality: coverage, precision, freshness, drift
uv run morphogen-compose --environment sandbox [--once] [--dry-run]   # orchestrator (needs Docker)
uv run python -m morphogen.mcp.server   # map MCP server (stdio)
```

## Working rules for this repo

- Out of scope for now: embodied fast loop, open web catalog discovery (configured registries only), multiple targets, product/UI polish.
- Every new event type gets a JSON Schema in `schemas/events/` and an entry in `contracts/intake.asyncapi.yaml`.
- Every settled design choice gets a decision record (`/adr`).
- Before finishing a change, run the `invariant-reviewer` subagent.
