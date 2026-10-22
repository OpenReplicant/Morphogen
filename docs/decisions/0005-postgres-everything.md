# 0005 Postgres for everything

Status: accepted, pending spike · 2026-10-22

**Decision.** One Postgres: relational (cognee metadata, approvals, catalog index), vectors (pgvector), graph (Apache AGE). PostgREST serves the UI through a read-only role over curated views. Row-level security is the intended mechanism for authority.

**Why.** One operational footprint, extensions, RLS, LISTEN/NOTIFY for live UI updates.

**Caveat.** cognee's built-in Postgres graph store is a demo feature without Cypher search types. We use AGE through the community pgGraph adapter or our own. Fallback: Neo4j for the graph tier only.

**Rule.** PostgREST never writes. Writes go through the intake.
