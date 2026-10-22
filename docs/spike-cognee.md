# Spikes (week 1)

Goal: find out where cognee and Postgres fit the model, and how thin our domain layer can stay. Write results into `docs/spike-results.md`.

## cognee on Postgres + AGE

| # | Feature | Pass criterion |
| --- | --- | --- |
| 1 | Couplings as nodes | A Coupling DataPoint joins two Port DataPoints; traversal slot→port→coupling→port→slot works in one query |
| 2 | Heavy edge/claim metadata | Provenance, confidence, status, level, environment stored and filterable |
| 3 | Bitemporal claims | Query "as of valid time T, as recorded at time R" returns correct results |
| 4 | Retraction | Closing a claim's valid time keeps history; current views exclude it |
| 5 | Changed-ID reporting | A pipeline run can report the node/edge IDs it created, changed, retired (natively or via wrapper) |
| 6 | Access control | `map` dataset writable only by the ingestor identity; agents can read `map` and write only `agent-memory-*` |
| 7 | Graph backend | AGE via the community pgGraph adapter (or our own) supports Cypher patterns watchers need; record latency at 100k claims |

Fallback if 7 fails: Neo4j for the graph tier only, behind the same domain layer. If 3–5 fight cognee's model: keep claims in our own Postgres tables and use cognee for extraction, embeddings and search.

## Intake router

Can OTel Collector exporters plus a minimal Python fan-out cover routing without becoming a bus? Pass: ingest, archive and one watcher subscription with no extra broker.
