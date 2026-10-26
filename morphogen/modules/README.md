# Morphogen modules (bootstrap set)

Each module is a provider of one of Morphogen's slots (`../distribution.yaml`): a `provider.yaml`, a
`migration.sql` giving it its own role and agent, tests, and no writes except change sets. Actuators never
submit claims; their effects are observed.

| Module | Slot | Status | Source |
| --- | --- | --- | --- |
| observer-otel | observer | Written (T5) | New: OTLP/HTTP receiver; observations shaped as rebuild 4 `observer-prometheus` |
| anomaly | analyser | Ported (T5) | rebuild 4 `anomaly`; follows the change feed from a durable cursor (T15, R5-34): each change set's latest windows, judged once |
| planner | planner | Written (T5) | Rewrite of rebuild 4 `skill-adaptation-planning`: the fixed action list, a prediction and a risk class |
| lane-autonomy | lane-policy (kernel slot) | Written (T5) | New: review forced for plan steps; autonomy level x risk class picks the lane |
| intent-actuator | actuator | Written (T5) | Rewrite of rebuild 4 `actuator-compose`: approval rules ported, commits to `../intent/` |
| prediction-verifier | outcome-verifier | Written (T5) | New |
| builder | builder | Written (T6) | New: a build request becomes a candidate in `../intent/experiments/` (fixture, or an agent harness) |
| sandbox | sandbox | Written (T6) | New: the slot's contract, then candidate and incumbent measured on a copy of the record; the evaluator records the scores |
| interview-encoder | design-agent | Ported (T13) | rebuild 4 `encoder-interaction`, unchanged but for names: a conversation as notes an interviewer quotes |
| design-blueprint | design-agent | Written (T13) | New: a described system with no open question becomes a review-lane plan to write its compose file (`morphogen.blueprint`) |
| map-gaps | gap-finder | Written (T13) | Rules new (system maps), shape from rebuild 4 `map-gaps`; 15 contract cases, 13 mutants |
| gaps-shacl | gap-finder | Written (R5-O18 proof) | New: the same rules as warning shapes of the kk-tosca pack (`kernel/packs/kk-tosca.shapes.ttl`), applied by a finder that knows no domain; no service yet, not the default |
| encoder-compose | system-encoder | Written (T9) | New: a compose file as a TOSCA topology, every claim citing its line; `scan --adopt` asks a person to approve a file brought in as it is (T26) |
| runtime-compose | runtime | Written (T9 as deploy/compose.py; T26, T27) | New: runs a system's compose file as committed, only when a person approved that file (morphogen.plans.approval); the runtime case set (16 cases, 11 mutants) on a stub engine |
| observer-prometheus | observer | Written (T9) | rebuild 4 `observer-prometheus`: request times from a service's metrics |
| registry-lookup | catalog-lookup | Written (T14, T20) | New (R5-30): component sets of any kind searched through adapters (`components`, `pypi`, `providers`); rules are toggles judged on every entry; an offered, pinned provider for a build request becomes a sandbox candidate; needs are matched against recorded entries by their requirements, deterministically (T20, R5-33) |

The reconciler that runs the services an environment's intent describes is `../deploy/reconcile.py`.

```sh
python3 morphogen/modules/install.py <db>          # kernel, the kernel providers Morphogen uses, every module
sh morphogen/contract/run.sh [--mutants]                  # the case sets of Morphogen's slots (analyser, gap-finder, runtime)
PGHOST=... PGUSER=... python3 morphogen/modules/test.py   # each module's tests, then the T5 loop, G2, G3 and the design agent
```
