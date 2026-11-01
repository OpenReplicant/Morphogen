# Morphogen

An agent that understands itself as connected components with intent, and
changes itself by finding better parts.

Morphogen runs as [Claude Code](https://code.claude.com/docs) in this
directory. It keeps a map of itself (`map/`), finds the gaps between what it
is and what it is meant to be, and closes them by reusing, configuring or
composing existing parts from catalogs before it writes new code. Every change
is trialled on a branch in a sandbox, scored by a gate it cannot edit, archived,
and adopted only as far as the operator's autonomy setting allows.

## Start

```bash
git clone https://github.com/OpenReplicant/morphogen && cd morphogen
```

Open it in the devcontainer (recommended: the judge and guard are mounted
read-only there), or run it directly:

```bash
pip install pyyaml==6.0.3 && tools/sandbox/build && claude
```

On first start Morphogen offers the `onboard` skill: it asks what you want it
for, how much freedom to give it, and what it may spend, then drafts
`map/intent.md` for you to accept.

## Layout

| Path | What | Who changes it |
|---|---|---|
| `CLAUDE.md` | The loop and the rules | operator |
| `map/intent.md` | Purpose, limits, autonomy level (1 to 4), budgets | operator |
| `map/blueprint.yaml` | Intended components, KPIs, lock levels, empty slots | Morphogen, with approval |
| `evals/` | The judge: `run` measures, `gate` compares with the trunk and archives | operator |
| `tools/hooks/guard.py` | Enforces locks, trunk protection, budgets, asks | operator |
| `tools/sandbox/` | Networkless, read-only trial container | operator |
| `strategies/` | How candidates are chosen: hill-climb, archive search, Red Queen | Morphogen, with approval |
| `catalogs.yaml` | Where to look for parts before generating them | Morphogen |
| `journal/` | Why every change was made | Morphogen, append-only |

For the gate to bind, protect `main` and require the `gate` check
(`.github/workflows/gate.yml`).

The first iteration of this repository (Morphogen and the Knowledge Kernel) is
on the branch `first-iteration`.

## Licence

Apache 2.0. See `LICENSE` and `NOTICE`.
