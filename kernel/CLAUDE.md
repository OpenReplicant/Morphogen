# Kernel rules (apply to everything under kernel/)

- Nothing here imports or references `morphogen/`. `python3 scripts/check_boundary.py` from the repo root.
- Every concern is a slot in `blueprint/slots.yaml` with an interface in `src/kk/interfaces.py` and a default provider in `providers/`.
- Core slots (record store, write pipeline) change only with a provider that passes `contract/run.sh`.
- Changing `contract/invariants.yaml` needs the owner's decision (`../docs/decisions.md`).
- No extension code inside the commit. Before: transform, veto, route. After: consume the change feed on a cursor.
- Port from rebuild 4 (OpenReplicant/kernel) rather than rewriting from memory; read `../docs/LESSONS.md` first.
