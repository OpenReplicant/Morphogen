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
5. `docs/decisions.md`: this rebuild's decisions; rebuild 4's D-01 to D-93 stay settled unless superseded.
6. `docs/LESSONS.md`: traps earlier rebuilds hit. Read before touching Postgres, MCP, Docker or evals.

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
pip install -r kernel/contract/requirements.txt                       # once, in a virtualenv (KK_PYTHON=<its python>)
PGHOST=<socket or host> PGUSER=<superuser> sh kernel/contract/run.sh   # conformance: 66 record + 13 validator + 17 belief cases
PGHOST=... PGUSER=... python3 kernel/contract/mutants.py                # every mutant must fail (38 today)
PGHOST=... PGUSER=... python3 kernel/providers/test.py                  # each provider's tests + services end to end
sh morphogen/contract/run.sh [--mutants]                               # Morphogen's slot contracts (analyser: 14 cases, 10 mutants, the sandbox also runs them as service cases; gap-finder: 10 cases, 8 mutants)
PGHOST=... PGUSER=... KK_RUN_AS=kkrun1,... KK_SANDBOX_CLUSTER=... python3 morphogen/modules/test.py # as root: each module's tests + the T5 loop + G2 + G3 + the design agent (T13) (model code runs as KK_RUN_AS behind nftables, on the sandbox's own cluster, R5-24/26; G3 needs Docker, R5-25)
KK_EVAL_CACHE=... python3 kernel/evals/scifact/run.py fetch|setup DB|retrieval DB   # recall floor (not in CI)
PGHOST=... PGUSER=... python3 kernel/evals/self-model/run.py setup DB && ... reference DB    # self-model questions (12, G7 >= 90%); morphogen/evals/self-model/run.py for Morphogen's 12; `claude DB` asks Haiku
PGHOST=... PGUSER=... python3 morphogen/evals/design/run.py setup DB && ... claude DB   # the interview with Haiku as the interviewer (R5-29)
python3.12 morphogen/evals/rcaeval/run.py run --dataset re1-ob --method analyser   # RCAEval floor (not in CI; EXPERIMENTS.md)
python3 scripts/check_boundary.py                                      # kernel/ never depends on morphogen/
```

## Layout

```
kernel/                    ← becomes its own repository
  contract/                invariants.yaml (the guarantees as named cases), slots/ (per-slot case sets), run.sh, mutants.py;
                           every slot in the blueprint names its contract (R5-21)
  blueprint/slots.yaml     the kernel's own slots, couplings and defaults
  schemas/                 change set and module manifest (wire formats)
  src/kk/interfaces.py     slot interfaces
  providers/               default providers for kernel slots (record-postgres ported; more to port)
  packs/                   vocabulary packs (PROV, SOSA, ORG, DQV, TOSCA mirror, ...)
morphogen/                 the distribution
  distribution.yaml        kernel slots used, application slots declared, providers chosen
  contract/slots/          case sets for Morphogen's slots (analyser); run.sh
  modules/                 providers for Morphogen's slots (observer, planner, actuator, verifier, design agent, ...)
  skills/                  how an agent does Morphogen's model-driven parts (interview)
  intent/                  desired state orchestrators reconcile; policies (autonomy x risk); systems/ (managed systems' compose files, R5-25)
  ui/, deploy/
docs/                      rebuild-5.md, decisions.md, LESSONS.md, slots-rebuild4.yaml
scripts/                   check_boundary.py
```
