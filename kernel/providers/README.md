# Default providers for kernel slots

Each provider is a directory with a manifest (`provider.yaml`, valid against `../schemas/module.schema.json`
once adapted), its code or migrations, and its tests. A provider for a core slot (record store, write
pipeline) must pass `../contract/run.sh <provider>`.

| Provider | Slot(s) | Status |
| --- | --- | --- |
| record-postgres | record-store, write-pipeline, lane-policy (review rules), change-feed (applied-sequence cursor), as-of reads | Ported from rebuild 4 `kernel/schema`, plus the feed and `api.claims_as_of` (T1); 54/54 contract cases; 14 mutants in `tests/mutants.py`, all fail |
| filter-gitleaks | intake-filter | To port (rebuild 4 `modules/ingest-filter-gitleaks`) |
| validator-schema | validator | To write; SHACL validator as a candidate |
| belief-corroboration | belief-model | To port |
| verifier-quotes | verifier | To port |
| truth-maintenance | truth-maintenance | To port |
| recall-bm25 (+ dense, re-rank opt-in) | recall | To port (`recall-index`, `recall-dense`) |
| kernel-mcp | agent-interface, context-assembler | To port |
| pack-loader | vocabulary-pack | To port |
| self-encoder | self-encoder | To rewrite |
| evaluator | evaluator | To port |
| claude-code | harness-adapter | To port (`kernel-mcp/hooks`) |
