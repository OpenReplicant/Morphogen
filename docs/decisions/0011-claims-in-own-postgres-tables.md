# 0011 Claims in our own Postgres tables; cognee optional

Status: accepted · 2026-10-22

**Decision.** The map is a bitemporal claim table (`map.claims`) in the Postgres from 0005, behind a `MapStore` interface (`src/morphogen/store/`) with a Postgres provider and an in-memory provider for tests. Ontology types are plain pydantic models whose references are identity keys. cognee moves to an optional extra (`uv sync --extra cognee`) for extraction, embeddings and search over the map later; it is not on the write path. This is the fallback that 0004 named.

**Why.** The spike's items 3–5 (bitemporal queries, retraction, changed-ID reporting) and 6 (single-writer access control) are the core of the model, and they fall out of a plain table with `valid_from/valid_to/recorded_at/record_to` plus Postgres roles: every change is an insert, a closed version is a new row, and the write path reports created/changed/retired IDs directly. cognee 1.x's `DataPoint` reserves fields we used (`type`), adds multi-user auth by default, and costs ~10 s to import; none of that helps the claim model. Couplings stay nodes (0001): a `Coupling` row references port and slot keys.

**Consequences.**
- Supersedes 0004. 0005 stands; AGE and pgvector stay in the image for the graph tier and search, unused by the claim store.
- Writes go through `MapStore.upsert/retire/touch`, called only by ingestors (invariant 1). Watchers, the promoter and the MCP server open the store with the reader role.
- "Agent memory" datasets (0004) remain the harnesses' business (cognee-memory plugin or cognee MCP); they never touch `map.claims`.
- Revisit when the graph tier needs Cypher at scale (spike item 7, not run: no AGE in the dev container).
