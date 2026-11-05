# Cognitive model: the Common Model of Cognition on Claude Code

Claude as the central pattern matcher and action selector, with the modules of the Common Model
of Cognition (Laird, Lebiere and Rosenbloom 2017, "A Standard Model of the Mind", AI Magazine
38(4), doi:10.1609/aimag.v38i4.2744) built from Claude Code's primitives: hooks, skills, MCP
servers, subagents. The spec was mapped with rebuild 6; [FINDINGS.md](FINDINGS.md) has what the
mapping found, and [rebuild-6-map/](rebuild-6-map/) the map itself, in rebuild 6's list format.

## Modules

| Module | Is |
|---|---|
| `cmc` | the whole: central selector, the modules below, the harness, the operator, evaluation |
| `wm` | working memory: named buffers, each holding at most one chunk (imaginal up to five) |
| `pm` | procedural memory: skills as explicit productions over the model's implicit procedures |
| `dm` | declarative memory: semantic and episodic chunks; one best chunk per cue, by activation |
| `percept` | perception: senses feed the percept buffer, compressed |
| `motor` | motor: write-side tools are the only way to change the world |
| `cycle` | the cognitive cycle: one model step between tool batches |
| `learn` | learning: online and gated |

Declarative memory's store is the [catalog](../catalog/BRIEF.md): entities, resolved, classified,
with claims and trust.

## Points

Agent-owned, tunable within ranges:

| Parameter | Of | Spec value |
|---|---|---|
| decay `d` | activation | 0.5 |
| `beta`, noise, retrieval threshold, source weights `W_k` | activation | unset |
| `alpha` | utility update | 0.2 |
| starting utility | utility table | 0.5 |
| candidates | candidate ranking | 3 |
| minimum repeats; "high reward" | chunking | 3; unset |
| failure reward | failure credit | unset |
| evict after cycles | working-memory decay | 8 |
| snapshot characters | injection | 2,000 |

Operator-owned, never changed by a candidate: buffer capacities (goal, retrieval, percept, motor
1; imaginal 5), pruning floor (0.2) and minimum fires (10), promote and demote thresholds
(unset), maximum continuations (2), and the reward judge's model.

Eight parameters are unset in the spec; each needs a value or a range before it can be tuned.

## Measure

- Task success on a fixed task set, with and without each module, scored by a judge outside the
  model (the spec's own reward has the model judge its own success: a gap the map found).
- Cost: tokens observed from outside, through a model gateway.
- Every trial starts from the same learned state: the memory store is reset between trials.

## Gaps the map found

- `cmc/evaluation` is empty: paired comparison, learned-state reset and token cost.
- `dm/vector-index` and `pm/candidate-ranking` need semantic retrieval the spec does not name.
- `learn/reward` is judged by the model itself.
- Hook facts to design around (from the Claude Code hooks reference, read 2026-11-03): an
  `additionalContext` over 10,000 characters is saved to a file with a 2,000-character preview,
  so the formatter must enforce working-memory capacity; SessionStart also fires on `clear` and
  `fork`; FileChanged cannot add context; hooks and servers writing one SQLite file need WAL and
  a busy timeout.

## Order

1. Entity resolution, then the catalog, as declarative memory's store.
2. The evaluation slot: a fixed task set, learned-state reset, outside token cost.
3. The modules, one at a time, each with its interface tests.
4. Morphogen tunes the agent-owned parameters, then tries structural changes between modules.

## Done when

The with/without comparison runs on the fixed task set, from a reset state, with token cost
observed from outside, and Morphogen produces at least one verdict on an agent-owned parameter.
