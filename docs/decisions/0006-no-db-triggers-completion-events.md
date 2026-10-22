# 0006 No database triggers or change capture; completion events instead

Status: accepted · 2026-10-22

**Decision.** Watchers are external processes. They subscribe to intake items (cheap match) and to completion events published after every ingest pipeline run. Completion events carry the IDs created, changed and retired, so graph queries anchor on what changed. Sweep watchers run on a schedule for structural patterns.

**Why.** Triggers and CDC bind us to cognee's internal storage layout and one backend. Completion events stay backend-agnostic and carry better context.
