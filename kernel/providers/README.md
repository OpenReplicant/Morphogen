# Default providers for kernel slots

Each provider is a directory with a manifest (`provider.yaml`, valid against `../schemas/module.schema.json`
once adapted), its code or migrations, and its tests. A provider for a core slot (record store, write
pipeline) must pass `../contract/run.sh <provider>`; so must a provider of any slot with a case set in
`../contract/slots/`. `provider.yaml` names its slots and its `runner`, which prints `ok: <case>` per passing
case; each provider's `tests/mutants.py` lists the mutants `../contract/mutants.py` checks. `install.py` puts the
record and providers' migrations into a database; `test.py` runs every provider's own `tests` and the
end-to-end service test (`tests/test_services.py`). Services share `kk.lib` (`../src/kk/`): validators
`listen` (before the commit), feed consumers `follow` the change feed (after it).

| Provider | Slot(s) | Status |
| --- | --- | --- |
| record-postgres | record-store, write-pipeline, lane-policy (review rules), change-feed (applied-sequence cursor), as-of reads | Ported from rebuild 4 `kernel/schema`, plus the feed and `api.claims_as_of` (T1); 54/54 contract cases; 14 mutants, all fail |
| filter-gitleaks | intake-filter | To port (rebuild 4 `modules/ingest-filter-gitleaks`) |
| validator-shacl | validator | Ported from rebuild 4 `modules/validator-shacl` (core, shapes, service) (T2, T3); 13/13 contract cases plus the shape tests; 8 mutants, all fail. Default until a JSON Schema validator passes the same set (R5-11, R5-O1) |
| belief-corroboration | belief-model | Ported from rebuild 4 (T2, T3): scoring unchanged, the service follows the change feed; 17/17 contract cases; 8 mutants, all fail |
| verifier-quotes | verifier | Ported from rebuild 4 (T3): checks unchanged (17/17), the service follows the change feed |
| (none) | truth-maintenance | Unfilled: Morphogen does not need it (`why` in `../blueprint/slots.yaml`, R5-12) |
| recall-bm25 | recall | Ported from rebuild 4 `recall-index` (T3); SciFact retrieval nDCG@10 0.6606, recall@200 0.9382 (floor 0.6594 / 0.9349; `../evals/scifact`). Dense fusion and re-ranking: opt-in, not ported |
| kernel-mcp | agent-interface | Ported from rebuild 4 (T3): the operator tools; `whoami` fixed for non-reviewers. Not ported: the memory profile and briefing (R5-12) |
| pack-loader | vocabulary-pack | Ported from rebuild 4 (T4): `packs.sql` identical but for file paths; the pack checks pass |
| self-encoder | self-encoder | Rewritten (T4): blueprint, provider manifests and a distribution as claims; `answer` says which provider fills each slot, citing file and line |
| evaluator | evaluator | Ported from rebuild 4 unchanged (T3): eval runs as DQV measurements. Candidate-vs-incumbent scoring comes with G2 |
| claude-code | harness-adapter | To port (`kernel-mcp/hooks`) |
