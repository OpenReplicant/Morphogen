# System Mapping and Adaptation Architecture

Repo copy of the live design doc. When they disagree, update this file and note it in a decision record.

## At a glance

The system models anything as **slots and couplings**, holds everything it knows in one knowledge store, and changes the world only through declarative intent that orchestrators reconcile. Observations arrive through standard intakes (OpenTelemetry, CloudEvents); capabilities stay direct (MCP, HTTP) and are discovered through the map. It adapts what it maps through a MAPE-K loop whose changes are tested as hypotheses before promotion, starting with itself.

Two use cases led here independently, adapting software systems and an embodied agent that learns; both reduce to this core. Mapping is what makes the model self-expanding.

Invariants: see `CLAUDE.md`.

## Architecture

```
 World ──► Sources (OTel, events) ──► Intake (OTLP, CloudEvents) ──► Ingestors (pipelines) ─────────► Knowledge (map)
   ▲                                        │                                                          │
   │                                   Raw archive                                               Watchers (match, then query)
   │                                                                                                   │
 Orchestrators ◄── Intent repo (git) ◄── Review / promoter ◄────────── proposals ◄─────────────────────┘
```

## MAPE-K mapping

| Phase | Slots | Boundary |
| --- | --- | --- |
| Monitor | OTel instrumentation and Collector, CloudEvents sources, bridges, ingestors | Sources only emit; ingestors are the only map writers |
| Analyze | Event watchers, sweep watchers | Read-only; output is findings and alerts as events |
| Plan | Proposal authors (agents, people), blueprint and hypothesis tooling | Output is a proposal event, never a change |
| Execute | Promoter, intent repo, orchestrator adapters | Only approved proposals become commits; only orchestrators act |
| Knowledge | Map store (bitemporal claims) + slots-and-couplings ontology; raw archive | Claims carry provenance, confidence, environment, status, level |
| Verify | Observation of the result vs predictions | Success is decided by observation |

Timescales: goal reasoning slow (agents, review), change planning medium (watchers, proposals), component control fast (orchestrators, components). Agents stay out of the hot path.

## Integration points and transport topology

| Point | Standard | Carries |
| --- | --- | --- |
| Telemetry in | OTLP via OTel Collector | Traces, metrics, logs, resource identity |
| Events in | CloudEvents over HTTP | Domain events, proposals, findings, blueprints, assertions |
| Capabilities | MCP / HTTP declared on slots | Called directly, never through the intake |
| Intent out | Git | Declarative files orchestrators reconcile |

- Discoverability belongs to the map: slots declare interfaces (MCP manifest, OpenAPI, AsyncAPI).
- OTel traces reveal observed couplings; semantic conventions give resource identity.
- **Transport topology is optional**: a coupling's realization is a slot graph of hops (endpoint, collector, broker, bridge) with protocol bindings. Absent: nothing degrades. Present: failure domains and contract-vs-reality drift become queries.
- A bus (Zenoh by default) is a provider for couplings that need one: ROS 2 cells, edge devices, high-volume fan-out. Bridges convert to OTLP/CloudEvents at the intake.

## Ontology and knowledge

Core concepts: Slot, Provider, Port, Coupling (a node), Requirement, Capability, Realization, Scope, Environment, Hypothesis, Prediction, Experiment. Slots/providers align with BFO roles/bearers; requirement/capability from TOSCA; first-class connectors from Acme. Aligned standards: OTel semantic conventions, SOSA/SSN, PROV-O; AsyncAPI/OpenAPI/MCP manifests as port contracts. Types are pydantic models (`src/morphogen/domain/ontology.py`) stored as rows of a bitemporal claim table (decision 0011).

### Claims

| | Instance | Type |
| --- | --- | --- |
| observed | Seen in the world | Type seen in use (catalog entry with verified results) |
| intended | Committed to intent | Type approved for a slot |
| hypothetical | Blueprinted or proposed | Catalog entry not yet tried |

Every claim carries provenance (discovered, asserted, inferred), confidence, environment, source.

### Time: bitemporal

Valid time (true in the world) and record time (when learned). Claims are never overwritten; changes close the old valid interval and open a new one. Drift = intended-not-observed or observed-not-intended at a valid time.

### Belief

Confidence is a pluggable function of supporting/contradicting observations, source trust and age. Conflicts are kept as sibling claims and flagged. Retraction is a claim. Experiment verdicts update belief the same way.

### Where data lives

Knowledge: the map store (`map.claims` in Postgres, behind `MapStore`; decision 0011); cognee optional for extraction and search, pgvector + AGE available for search and the graph tier. Raw history: time-series and object stores via Collector exporters and the event archiver. The graph holds claims about raw data, never raw data.

## Write path and reaction

- **Intake**: OTLP receiver + CloudEvents HTTP endpoint; a small router fans out to ingestors, the raw archive and subscribed watchers.
- **Ingestors** (only map writers): validate against contract → map to claims → attach provenance/confidence/environment/status/level → resolve identity (`morphogen.slot` span attribute, then OTel `service.name`), dedupe → `MapStore.upsert`/`retire` → publish a **completion event** with IDs created/changed/retired.
- Writes originating elsewhere (belief, promotion, retraction, catalog notes) are events an ingestor writes.
- **Event watchers**: cheap match, then graph query anchored on changed IDs. **Sweep watchers**: scheduled structural checks (unobserved slots, drift, coverage gaps, couplings without contracts, hypotheses without predictions). Watchers emit findings/alerts/proposals with `causationid`; never write, never act.

## Governance

Policy engine decides per proposal from autonomy level × risk class (see `intent/policies/autonomy.yaml`). Irreversible always needs a person. Targets start at L0, promote on a verified record, demote automatically on failed verification or rollback. Guards: kill switch, rate limits and cooldowns with hysteresis, blast-radius budget, preconditions re-checked before commit, policy as code on read-only mounts.

## Change path

Proposal → review/promoter → commit to `intent/` → orchestrator reconcile → observation → watcher compares to predictions. Rollback is another commit.

Agent isolation (runtime-enforced): graph read via MCP; send proposals/findings/alerts to intake only; workspace read-write; control plane and approvals read-only mounts; no intent write; no credentials.

## Scientific loop

Map or blueprint → implement (provider from requirements and contracts; contract tests generated) → hypothesis with predictions → sandbox experiment (replay from archive or mirrored traffic) → observe and compare → update belief → promote (sandbox, canary, full). Every experiment has a control; predictions are statistical; replay stubs side effects.

## Catalogs

Catalog entries are provider **types** (TOSCA node types) with capabilities, requirements, port contracts, transports, license, source, trust. Kinds are tags: provider, transport, contract, pattern, plus domain kinds. The plugin registry is the internal catalog's view of what is installed. Catalog adapters ingest through normal pipelines. Large public catalogs are federated (queried at resolution time). Supply chain: signatures and provenance, SBOM, sandbox-first use.

Resolution: unmet requirement → catalog query → hypothetical providers (or a build task) → scientific loop. Configured registries (including private ones) are in scope now; open web discovery of new catalogs comes later and never auto-subscribes.

## Design agent

Elicit → draft slot-and-coupling graph (hypothetical claims) → correct in the UI → check (unfilled slots, unmet requirements, contract mismatches) → resolve from catalogs → build and test. Systems without OTel enter through CloudEvents adapters; human statements are `asserted`, low confidence.

## Extensibility and UI

One plugin registry (Tasks/Pipelines, watchers, transport providers/bridges, orchestrator adapters, observers, UI views). The UI is an Alpine.js + daisyUI window-manager shell; views (our panels plus third-party UIs: cognee, database consoles, Grafana) run behind Caddy with forward_auth SSO and are listed from the catalog. First views: graph explorer, review queue, experiment timeline, blueprint panel.

## Embodied profile (later)

Bodies and minds are providers for slots; ROS 2 is the body interface; the 10–30 Hz control loop runs inside a cell over Zenoh, posts derived facts at event rate, and learns inside a declared policy envelope. Structural changes use the adaptation path.

## Open decisions

- Identity across non-OTel sources (OTel resource attributes are the first key).
- Authority: who may publish, approve, read what (Postgres RLS is the likely mechanism).
- Retention/compaction of closed claims.
