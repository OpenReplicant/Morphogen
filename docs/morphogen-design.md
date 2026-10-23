# Morphogen design notes (from the Oct 22–23, 2026 design sessions)

The design that led to rebuild 5. The record-and-guarantees side is settled in `rebuild-5.md` and
`decisions.md`; this file holds the Morphogen-side design those documents only summarize. Where this file and
`decisions.md` disagree, `decisions.md` wins. Live copies (claude.ai docs, not readable from Claude Code):
"System Mapping and Adaptation Architecture" and "Rebuild 5: Kernel and Morphogen Carry-Over Map".

## What Morphogen is

A MAPE-K loop over a map. Systems are modeled as **slots and couplings**; the loop observes them, analyses,
plans changes as hypotheses, executes through intent, and verifies by observation. Mapping comes first: the
ability to map a system is the ability to understand and work on it. Two use cases arrived here
independently (adapting software systems; an embodied agent that learns) and reduce to the same core.

## Model (maps onto rebuild 4's TOSCA mirror, D-07)

| Concept | Meaning |
| --- | --- |
| Slot | A role in a context (not a container): filled by a service, API, MCP server, device, person or model |
| Provider | What fills a slot; may itself be a slot graph |
| Port | Named input/output with a payload type and contract |
| Coupling | A node, not an edge: type (call, event, stream, shared state, request/reply), contract, observations, history |
| Requirement / capability | What a slot needs / what a provider offers; matching generates candidates |
| Realization | Optional slot graph of how a coupling travels (hops, protocol bindings). Absent: nothing degrades. Present: failure domains and contract-vs-reality drift become queries (WoT owns transports, D-07) |

Claims about the map carry status **observed / intended / hypothetical** and level **instance / type** (catalog
entries are types). Drift = intended-not-observed or observed-not-intended.

## Integration points

| Point | Standard | Notes |
| --- | --- | --- |
| Telemetry in | OTLP via the OpenTelemetry Collector | Traces reveal observed couplings; semantic conventions give resource identity |
| Events in | CloudEvents over HTTP, carrying change sets | Systems without OTel enter through adapters; statements from people are testimony with low belief |
| Capabilities | MCP and HTTP, declared on slots | Called directly; discovered through the map, never through a bus |
| Intent out | Git | Orchestrators (Compose, Nomad, Kubernetes) reconcile; the actuator never claims success |

No message bus in the core. Zenoh is the default where a bus is needed (ROS 2 cells via rmw_zenoh, edge
devices), behind a bridge to the intake. The bridge is itself a slot.

## Catalogs and resolution

Catalog entries are provider types with capabilities, requirements, contracts, transports, licence, source
and trust. Kinds are tags (provider, transport, contract, pattern). Configured registries, including private
ones (container registries, PyPI, MCP registry), are searched from a slot's role and requirements; matches
become hypothetical providers, gaps become build tasks. Large public catalogs are queried at resolution time,
not mirrored. Supply chain: signatures and provenance, sandbox-first use. Open web discovery of new catalogs
comes later and never auto-subscribes. Candidates × configuration values form the experiment matrix for
exploring a parameter space.

## Design agent

Elicit (purpose, roles, interfaces, constraints) → draft slots and couplings as hypothetical claims → person
corrects in the UI → check (unfilled slots, unmet requirements, contract mismatches; rebuild 4's map-gaps) →
resolve from catalogs → build and test. The first milestone is design-first: the design agent blueprints
Morphogen itself; as parts are built and instrumented, observed claims appear beside the hypothetical ones.

## Scientific loop and governance

- Every plan is a hypothesis with statistical predictions (effect, window, minimum samples) and a control.
- Sandbox, then canary, then full. Replay stubs side effects.
- A separate verifier compares observations with predictions (invariant 5).
- Lane policy: autonomy level L0–L4 × risk class (`morphogen/intent/policies/autonomy.yaml`). Irreversible
  always needs a person. Promote a target on a verified record; demote on a failed verification or rollback.
- Guards: kill switch, rate limits, cooldowns with hysteresis, blast-radius budget, preconditions re-checked
  before commit, proposals expire.
- Agents run in containers without credentials or intent write access; mounts enforce it, hooks are convenience.
- Playbooks: consider Rainbow's Stitch model (strategies of tactics, with conditions, cost and utility).

## Embodied profile (later)

Bodies and minds are providers for slots; ROS 2 is the body interface (robots, simulators, game clients via
video capture). The 10–30 Hz control loop runs inside a cell, posts derived facts at event rate, and learns
inside a declared policy envelope; structural changes (new modules, drives, skills, bodies) go through the
adaptation path. Swappable minds make the LLM a baseline and control for the symbolic learner.

## UI

A window-manager shell (Alpine.js + daisyUI) whose views are providers listed from the catalog; third-party
UIs (database consoles, Grafana) open as windows behind Caddy with single sign-on. Views talk through a small
versioned postMessage contract.

## Prior art and positioning

- Backstage: a declared catalog; Morphogen checks whether it is true (drift against observation). Its entity
  kinds are a candidate software vocabulary; an adapter can ingest it as testimony.
- Port: closest commercial catalog-plus-actions; closed SaaS, software only, no observed-vs-declared or time.
- Dynatrace, Causely: observed topology and causal analysis; no governed change.
- Rainbow (CMU): architecture model plus MAPE loop; the intellectual ancestor.
- Keptn: archived by CNCF; a narrow loop tied to one domain did not hold an audience.
- cognee, Graphiti: model output becomes the record; reproduced as baselines (R5-06).
