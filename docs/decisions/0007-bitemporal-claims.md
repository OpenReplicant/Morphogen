# 0007 Bitemporal claims; status and level

Status: accepted · 2026-10-22

**Decision.** Every claim has valid time and record time, a status (observed / intended / hypothetical) and a level (instance / type). Claims are never overwritten: a change closes the old valid interval and opens a new one. Retraction is a claim.

**Why.** Replay, drift, experiments and "what did we believe then" need both times. Separating level keeps catalog entries (types) apart from blueprints and deployments (instances).
