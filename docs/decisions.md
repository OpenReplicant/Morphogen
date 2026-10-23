# Decisions (rebuild 5)

Append-only. Rebuild 4's decisions (OpenReplicant/kernel, `docs/decisions.md`, D-01 to D-93) stay
settled unless an entry here supersedes one. Status: **decided** (owner agreed), **adopted** (taken on
recommendation; confirm or overturn), **proposed** (needs the owner).

| ID | Decision | Status |
| --- | --- | --- |
| R5-01 | **Rebuild 5 keeps the guarantees and changes the boundary.** The claim model, change sets, bitemporality, scopes and invariants carry over (D-01, D-02, D-05, D-09, D-10). The module boundary, the ontology weight and actuation change. See `docs/rebuild-5.md` | decided |
| R5-02 | **The kernel is a blueprint, not a monolith.** Every concern is a slot with an interface and a default provider; nothing has a built-in handler. Even the record store and the write pipeline are slots | decided |
| R5-03 | **Guarantees are a conformance suite.** The invariants are named, executable cases (`kernel/contract/invariants.yaml`). A core-slot provider is valid only if every case passes, and the suite must fail when a check is disabled | decided |
| R5-04 | **No extension code in the commit** (keeps D-86's reasoning). Hook points before the commit may transform, veto or route; after the commit, consumers read the change feed on a cursor and write only by new proposals | decided |
| R5-05 | **Morphogen is the only distribution for now.** Other uses (process intelligence, agent memory) are built with it later. The kernel is built inside the Morphogen repository under `kernel/`, never depending on `morphogen/`, and moves to its own repository when a second distribution needs it | decided |
| R5-06 | **cognee and Graphiti are baselines, not dependencies.** In both, model output becomes the record (Graphiti's LLM dedupes and invalidates on every write, with no switch; neither runs the guarantees). Their approaches are reproduced and scored on our evals; ideas credited in `docs/sources.md` | decided |
| R5-07 | **Actuation through intent.** Approved plans become commits to `morphogen/intent/`; orchestrators reconcile; outcomes are observed, never claimed by the actuator (extends D-53) | adopted — confirm |
| R5-08 | **Lane policy: autonomy level × risk class** (`morphogen/intent/policies/autonomy.yaml`). Irreversible changes always need a person | adopted — confirm |
| R5-09 | **Gates and the stop rule.** G1 contract, G2 self-modifying, G3 someone else's system. No kernel redesign before G1, no Morphogen redesign before G2 | decided |

## Open

| ID | Question | Recommendation |
| --- | --- | --- |
| R5-O1 | Keep the RDF/CURIE machinery (prefix table, SHACL in the write path) or move RDF to the edges (export, alignment)? A third of rebuild 4's lessons are prefix, pack and SHACL trouble | Edges: JSON Schema validator by default, SHACL as a candidate validator, N-Quads export kept |
| R5-O2 | Module boundary: Postgres roles reading `api` views (rebuild 4) or protocol contracts (change sets over HTTP, MCP)? | Both: roles stay the identity and clearance mechanism; modules may also submit over HTTP, so any language or harness can be a provider |
