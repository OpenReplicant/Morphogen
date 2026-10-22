# 0012 Compose orchestrator; intent commits carry trace context

Status: accepted · 2026-10-22

**Decision.** The first orchestrator adapter is Docker Compose (`src/morphogen/orchestrators/compose.py`, `morphogen-compose`). One adapter process per environment watches `intent/environments/<env>/` and runs `docker compose -p morphogen-<env> -f … up -d --remove-orphans` over every compose file there, in path order, when the files' content hash changes. A failed run is retried on the next pass. An empty folder brings the project down only with `--prune-empty`. The promoter adds a `Traceparent:` git trailer to each intent commit, and the adapter continues that trace when it reconciles.

**Why.** Content hashing keeps reconciliation idempotent and independent of whether `intent/` is a git repository. The trailer makes the promoter → orchestrator → docker hops observable in the self-map. Without it, the shared-state coupling through git would be permanent drift. Pruning is opt-in because an accidentally empty folder should not take down an environment.

**Consequences.** The adapter never reads the map (invariant 7) and holds the only Docker credentials. It runs on the Docker host, not in an agent's container (0008). Nomad and Kubernetes adapters implement the same `Orchestrator` protocol. The self-blueprint gains `orchestrator` and `container_runtime` slots (couplings c12, c13).
