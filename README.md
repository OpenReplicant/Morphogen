# Morphogen

A system you describe, which builds and manages it, starting with itself. An
[OpenReplicant](https://github.com/OpenReplicant) project, Apache-2.0.

Morphogen runs on the **knowledge kernel**, a governed record where model output is only ever a proposal:
every claim is attributed and referenced, nothing is deleted, clearance is enforced by the store, and no
method verifies its own output. The kernel is built here under `kernel/` and will move to its own repository.

- What this rebuild keeps and changes: `docs/rebuild-5.md`
- The guarantees, as tests: `kernel/contract/invariants.yaml`
- Slots and default providers: `kernel/blueprint/slots.yaml`, `morphogen/distribution.yaml`
- Decisions: `docs/decisions.md`
- Working rules: `CLAUDE.md`

```sh
PGHOST=<socket or host> PGUSER=<superuser> sh kernel/contract/run.sh   # conformance
python3 scripts/check_boundary.py                                      # kernel/ never depends on morphogen/
```
