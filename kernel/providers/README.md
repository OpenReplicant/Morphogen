# Default providers for kernel slots

Each provider is a directory with a manifest (`provider.yaml`, valid against `../schemas/module.schema.json`
once adapted), its code or migrations, and its tests. A provider for a core slot (record store, write
pipeline) must pass `../contract/run.sh <provider>`; so must a provider of any slot with a case set in
`../contract/slots/`. `provider.yaml` names its slots and its `runner`, which prints `ok: <case>` per passing
case; each provider's `tests/mutants.py` lists the mutants `../contract/mutants.py` checks.

| Provider | Slot(s) | Status |
| --- | --- | --- |
| record-postgres | record-store, write-pipeline, lane-policy (review rules), change-feed (applied-sequence cursor), as-of reads | Ported from rebuild 4 `kernel/schema`, plus the feed and `api.claims_as_of` (T1); 54/54 contract cases; 14 mutants, all fail |
| filter-gitleaks | intake-filter | To port (rebuild 4 `modules/ingest-filter-gitleaks`) |
| validator-shacl | validator | Ported from rebuild 4 `modules/validator-shacl` (core) and `shapes/` (T2); 13/13 contract cases plus the shape tests; 8 mutants, all fail. Default until a JSON Schema validator passes the same set (R5-11, R5-O1). Service: T3 |
| belief-corroboration | belief-model | Scoring model ported from rebuild 4 unchanged (T2); 17/17 contract cases; 8 mutants, all fail. Feed consumer: T3 |
| verifier-quotes | verifier | To port |
| truth-maintenance | truth-maintenance | To port |
| recall-bm25 (+ dense, re-rank opt-in) | recall | To port (`recall-index`, `recall-dense`) |
| kernel-mcp | agent-interface, context-assembler | To port |
| pack-loader | vocabulary-pack | To port |
| self-encoder | self-encoder | To rewrite |
| evaluator | evaluator | To port |
| claude-code | harness-adapter | To port (`kernel-mcp/hooks`) |
