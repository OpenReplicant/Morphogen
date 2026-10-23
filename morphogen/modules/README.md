# Morphogen modules (bootstrap set)

| Module | Slot | Status | Source |
| --- | --- | --- | --- |
| interview-encoder, map-gaps | design-agent | To port | rebuild 4 `encoder-interaction`, `skill-interview`, `map-gaps` |
| observer-otel | observer | New | — |
| observer-prometheus | observer | To port | rebuild 4 `observer-prometheus` |
| anomaly | analyser | To port | rebuild 4 `anomaly` |
| planning-skill | planner | To rewrite | rebuild 4 `skill-adaptation-planning`, plus predictions and risk class |
| intent-actuator | actuator | To rewrite | rebuild 4 `actuator-compose`; commits to `../intent/` instead of calling Docker |
| prediction-verifier | outcome-verifier | New | — |
| registry-lookup | catalog-lookup | New | — |

Every module: a manifest naming its slot, its own identity, tests, and no writes except change sets.
Actuators never submit claims; their effects are observed.
