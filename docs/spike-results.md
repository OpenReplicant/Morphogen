# Spike results (week 1)

Run in a dev container with Postgres 16 and no Docker daemon, so no AGE and no pgvector. Outcome: decision 0011 (claims in our own tables; cognee optional).

## cognee on Postgres + AGE

| # | Feature | Result |
| --- | --- | --- |
| 1 | Couplings as nodes | **Pass (own tables).** `Coupling` rows reference port and slot keys; `queries.blast_radius` traverses slot → coupling → slot. |
| 2 | Heavy claim metadata | **Pass.** Status, level, environment, provenance, confidence are columns; filterable in SQL and through `api.*` views. |
| 3 | Bitemporal claims | **Pass.** `tests/test_claims.py::test_change_closes_old_interval_and_opens_new` queries "as of valid T, as recorded at R". |
| 4 | Retraction | **Pass.** `retire()` closes the valid interval with a new row; history keeps every version; current views exclude it. |
| 5 | Changed-ID reporting | **Pass, native.** `upsert`/`retire` return created/changed/retired node and edge IDs; every pipeline run publishes them in `pipeline.completed`. |
| 6 | Access control | **Pass (roles).** Live run: intake writes as `morphogen_ingestor`, watchers/promoter/MCP read as `morphogen_reader`, governance written only as `morphogen_promoter`. Granting from the ingestor on promoter-owned views failed, as it should. |
| 7 | Graph backend (AGE) | **Not run.** No AGE in this container. Not needed by the claim store; revisit for watcher Cypher at scale. |

cognee 1.6.5 notes: `DataPoint` already defines `type` (our `Coupling.type` collided; renamed `coupling_type`), multi-user access control is on by default, import takes ~10 s, and `cognee[postgres]` needs `libpq` headers via `psycopg2` (worked around with `psycopg2-binary`).

## Intake router

**Pass.** OTel Collector (OTLP/HTTP to `/otlp/v1/traces`) plus the in-process `Router` covers ingest, archive (JSONL) and watcher subscription with no broker. The router wraps in-process publishes in an `intake` span so the self-map sees promoter → intake and drift-watcher → intake as designed.

## Live self-map (milestone 1, steps 1–10)

Intake under uvicorn with the real roles, its own spans exported back to `/otlp` (no Collector available), `morphogen-report` after an MCP proposal was approved and an `echo` service sent one span:

```
coverage      91%  (11 expected couplings)
precision     100%  (10 observed couplings)
drift         2 expected not observed, 0 observed not expected
  missing    coupling collector -> intake  [hypothetical] morphogen-self/c1
  missing    slot     collector  [hypothetical] morphogen-self/collector
```

The remaining drift is the Collector, which did not run here. Before the `echo` span, `echo` was listed as intended-not-observed. Earlier runs surfaced two real design gaps, both fixed: the drift watcher read through the ingestor's connection, and in-process publishes skipped the intake.
