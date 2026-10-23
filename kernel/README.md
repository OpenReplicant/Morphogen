# Knowledge kernel

A governed record where model output is only ever a proposal. Built inside the Morphogen repository and
designed to be extracted (`git filter-repo --path kernel/ --path-rename kernel/:`) once a second
distribution needs it. Nothing in this directory depends on `morphogen/`.

| Path | What |
| --- | --- |
| `contract/` | The guarantees as named, executable cases. Any provider of a core slot must pass them |
| `blueprint/slots.yaml` | The kernel's own slots, couplings and default providers |
| `schemas/` | Wire formats: change set, module manifest |
| `src/kk/interfaces.py` | Slot interfaces |
| `providers/` | Default providers. `record-postgres` is ported from rebuild 4 |
| `packs/` | Vocabulary packs |

Rule: every concern is a slot with a swappable provider; no extension code runs inside the commit.
