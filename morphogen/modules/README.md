# Morphogen modules (bootstrap set)

Each module is a provider of one of Morphogen's slots (`../distribution.yaml`): a `provider.yaml`, a
`migration.sql` giving it its own role and agent, tests, and no writes except change sets. Actuators never
submit claims; their effects are observed.

| Module | Slot | Status | Source |
| --- | --- | --- | --- |
| observer-otel | observer | Written (T5) | New: OTLP/HTTP receiver; observations shaped as rebuild 4 `observer-prometheus` |
| anomaly | analyser | Ported (T5) | rebuild 4 `anomaly`; `detect.py` unchanged, follows the change feed |
| planner | planner | Written (T5) | Rewrite of rebuild 4 `skill-adaptation-planning`: the fixed action list, a prediction and a risk class |
| lane-autonomy | lane-policy (kernel slot) | Written (T5) | New: review forced for plan steps; autonomy level x risk class picks the lane |
| intent-actuator | actuator | Written (T5) | Rewrite of rebuild 4 `actuator-compose`: approval rules ported, commits to `../intent/` |
| prediction-verifier | outcome-verifier | Written (T5) | New |
| builder | builder | Written (T6) | New: a build request becomes a candidate in `../intent/experiments/` (fixture, or an agent harness) |
| sandbox | sandbox | Written (T6) | New: the slot's contract, then candidate and incumbent measured on a copy of the record; the evaluator records the scores |
| interview-encoder, map-gaps | design-agent | To port | rebuild 4 `encoder-interaction`, `skill-interview`, `map-gaps` |
| observer-prometheus | observer | To port | rebuild 4 `observer-prometheus` |
| registry-lookup | catalog-lookup | New | — |

The reconciler that runs the services an environment's intent describes is `../deploy/reconcile.py`.

```sh
python3 morphogen/modules/install.py <db>          # kernel, the kernel providers Morphogen uses, every module
sh morphogen/contract/run.sh [--mutants]                  # the case sets of Morphogen's slots (analyser)
PGHOST=... PGUSER=... python3 morphogen/modules/test.py   # each module's tests, then the T5 loop and G2
```
