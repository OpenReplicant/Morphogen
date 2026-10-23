# Morphogen (rebuild 5)

Morphogen is a system you describe, which builds and manages it, starting with itself. It runs on the
**knowledge kernel**: a governed record where model output is only ever a proposal. The kernel is built
here under `kernel/` and will move to its own repository to serve other distributions.

## Starting a session

Run the `dev` skill (environment, reference clone, checks), then pick the next open task in `docs/rebuild-5.md` ("First tasks", T1 onward). One task at a time; each ends with its check passing and a PR.

## Read first, in this order

1. `docs/rebuild-5.md`: what carries over from rebuild 4, what changes, the gates and the stop rule.
2. `kernel/contract/invariants.yaml`: the guarantees. They are tests, not prose.
3. `kernel/blueprint/slots.yaml` and `morphogen/distribution.yaml`: every slot, its interface and default provider.
4. `kernel/src/kk/interfaces.py`: the slot interfaces.
5. `docs/morphogen-design.md`: the Morphogen-side design (integration points, catalogs, design agent, scientific loop, embodied profile, prior art).
6. `docs/decisions.md`: this rebuild's decisions; rebuild 4's D-01 to D-93 stay settled unless superseded.
7. `docs/LESSONS.md`: traps earlier rebuilds hit. Read before touching Postgres, MCP, Docker or evals.

Reference implementation (read-only): `OpenReplicant/kernel` (rebuild 4). Port from it; do not edit it.

## The split rule

- Anything another distribution could use lives under `kernel/`. Only Morphogen-specific parts live under `morphogen/`.
- `kernel/` never imports or references `morphogen/` (`python3 scripts/check_boundary.py`).
- An application slot moves from `morphogen/` to `kernel/` when a second distribution needs it.

## Kernel shape

- Every concern is a slot with an interface and a swappable default provider. Nothing has a built-in handler.
- Guarantees are the conformance suite (`kernel/contract/`). Core slots (record store, write pipeline) may be swapped only by a provider that passes it.
- No extension code runs inside the commit. Extensions act before it (transform, veto, route) or after it (consume the change feed on a cursor). Their outputs re-enter at intake as new proposals.

## Invariants (changing them needs the owner's explicit decision)

1. Every claim is attributed (agent + run) and referenced; extracted claims carry the supporting quote.
2. Nothing is deleted: supersede, refute or retract by status. Redaction keeps identity and lineage and is itself recorded.
3. A claim's scope is at least as restrictive as everything it was made from.
4. Clearance is granted by people and enforced by the store, never by a model's judgment.
5. No method verifies its own output.
6. Every answer cites claim ids and shows their belief.

## Stop rule

- No redesign of the kernel until gate G1 (contract) passes; no redesign of Morphogen until G2 (self-modifying) passes.
- New ideas go into `docs/decisions.md` as proposed entries, checked against rebuild 4's decisions first.
- Rebuild 4's eval numbers are the floor: a ported area is not done until it matches them.
- cognee and Graphiti are studied and reproduced as baselines, never added as dependencies.

## Working with the owner

- Recommend one option and keep moving. Ask only for decisions that are the owner's (kernel invariants, positioning, licences) and say what you recommend.
- When asked to be dialectical, give the strongest objections, then a synthesis that keeps what survives.
- Plain words. Don't write "...and it's worth...".
- Evals that need a model use OpenRouter `:free` models under 10B parameters and/or Haiku sub-agents; never paid models.
- Look things up; don't rely on memory for external tools. Pin exact versions at least two weeks old.
- Each task: implement, test, `sh kernel/contract/run.sh`, `python3 scripts/check_boundary.py`, run the `invariant-reviewer` agent, commit, PR.

## Checks

```sh
PGHOST=<socket or host> PGUSER=<superuser> sh kernel/contract/run.sh   # conformance: 30 cases today
python3 scripts/check_boundary.py                                      # kernel/ never depends on morphogen/
```

## Layout

```
kernel/                    ← becomes its own repository
  contract/                invariants.yaml (the guarantees as named cases), run.sh
  blueprint/slots.yaml     the kernel's own slots, couplings and defaults
  schemas/                 change set and module manifest (wire formats)
  src/kk/interfaces.py     slot interfaces
  providers/               default providers for kernel slots (record-postgres ported; more to port)
  packs/                   vocabulary packs (PROV, SOSA, ORG, DQV, TOSCA mirror, ...)
morphogen/                 the distribution
  distribution.yaml        kernel slots used, application slots declared, providers chosen
  modules/                 providers for Morphogen's slots (observer, planner, actuator, verifier, ...)
  intent/                  desired state orchestrators reconcile; policies (autonomy x risk)
  ui/, deploy/
docs/                      rebuild-5.md, morphogen-design.md, decisions.md, LESSONS.md, slots-rebuild4.yaml
scripts/                   check_boundary.py
```
