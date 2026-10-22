# 0008 Intent-only actuation

Status: accepted · 2026-10-22

**Decision.** The map is not the territory. Changes reach the world only as commits to `intent/` (written by the promoter), reconciled by orchestrators (Docker Compose first; Nomad and Kubernetes through the same adapter interface). The graph learns outcomes only from observation.

**Why.** Prevents the system from shortcutting reality: a change "worked" only when observed.

**Consequences.** Agents never hold orchestrator credentials or intent write access; this is enforced with container mounts, not prompts.
