# Morphogen

A system you describe, which builds and manages it, starting with itself. An
[OpenReplicant](https://github.com/OpenReplicant) project, Apache-2.0.

Morphogen watches the systems it manages, notices when something is wrong, proposes a fix with a stated
prediction, and carries it out once a person approves. Afterwards it checks whether the prediction held. It
can also propose a better version of one of its own parts, measure it in a sandbox, and swap it in after
approval.

Everything it knows and does goes through the **knowledge kernel**, a governed record where model output is
only ever a proposal. The kernel is built here under `kernel/` and will move to its own repository.

## The guarantees

These are enforced by the store and checked by a conformance suite (`kernel/contract/`), not left to
convention:

1. Every claim is attributed (agent and run) and referenced; extracted claims carry the supporting quote.
2. Nothing is deleted: claims are superseded, refuted or retracted by status. Redactions are recorded too.
3. A claim's scope is at least as restrictive as everything it was made from.
4. Clearance is granted by people and enforced by the store, never by a model's judgment.
5. No method verifies its own output.
6. Every answer cites claim ids and shows their belief.

## How the loop works

```
 observer ──▶ analyser ──▶ planner ──▶ review lane ──▶ actuator ──▶ reconciler
 (telemetry)  (anomaly)    (plan +      (a person      (commits     (runs what
                            prediction)  approves)      to intent/)  is committed)
      ▲                                                                   │
      └────────────── prediction verifier: did the prediction hold? ◀─────┘
```

- Each box is a **slot** with a swappable provider (`kernel/blueprint/slots.yaml`, `morphogen/distribution.yaml`).
- Providers write only by submitting change sets. The store validates them, applies them, and routes them
  to a person's review when the policy or risk asks for it.
- Extensions never run inside the commit. They act before it (validate, route) or after it (follow the change
  feed), and whatever they produce comes back in as a new proposal.
- Model-written code (a candidate provider) runs as an OS user of its own, behind its own firewall rules,
  against a database cluster of its own.

## What works today

| Area | State |
| --- | --- |
| Kernel record, validation, belief, change feed | Conformance suite passes: 72 record, 13 validator, 17 belief cases; every kernel slot has a shared case set (69 cases), 80 mutants killed; the wire API is versioned (1.0.0) |
| The loop on Morphogen itself (T5) | Observe, analyse, plan, approve, act, verify |
| Self-modification (gate G2) | A faster analyser was requested, built, measured, approved and verified live |
| A system Morphogen did not build (gate G3) | podinfo with Redis: mapped from its compose file, watched, settings changed through review |
| Design agent (T13) | An interview becomes a system map; gaps become questions; a complete map becomes a compose file |
| Catalog lookup (T14, T20) | Components found by stated requirements, matched deterministically |
| Review and loop UI (T21) | People sign in with their own login, approve or refuse plans, follow each plan to its verdict |
| Running locally (T22, T23, T24) | One command brings it up, in a container image or on the machine; a described system ends running once a person approves its file; Claude Code runs inside as a user of its own |
| Evals | SciFact recall, LongMemEval, RCAEval, self-model questions: see `docs/rebuild-5.md` for numbers and open gaps |

Plans and open items: `docs/rebuild-5.md` ("First tasks").

## Quick start

You need Postgres 16, Python 3.12 and, for the full module suite, Docker, nftables, gitleaks and Node with
Playwright. `docs/DEVELOPING.md` walks through each one.

```sh
python3 -m venv .venv && . .venv/bin/activate
pip install -r kernel/contract/requirements.txt -r kernel/providers/kernel-mcp/requirements.txt \
            -r morphogen/modules/observer-otel/requirements.txt -r morphogen/modules/registry-lookup/requirements.txt
export KK_PYTHON=$PWD/.venv/bin/python PGHOST=<socket or host> PGUSER=<superuser> PGPASSWORD=<its password>

sh kernel/contract/run.sh              # the kernel's conformance suite, every provider
python3 kernel/contract/mutants.py     # every deliberately broken provider must fail it
python3 kernel/providers/test.py       # each kernel provider's own tests, and the services end to end
sh morphogen/contract/run.sh           # Morphogen's slot contracts
python3 scripts/check_boundary.py      # kernel/ never depends on morphogen/
```

## Run it on your own machine

In a container (rootless Podman or Docker; nothing else to install):

```sh
podman build -f morphogen/deploy/container/Containerfile -t morphogen:dev .
podman run -d --init --name morphogen -p 127.0.0.1:8470:8470 -v morphogen:/var/lib/morphogen \
  -v morphogen-db:/var/lib/postgresql/data -v morphogen-agent:/home/agent \
  -v $XDG_RUNTIME_DIR/podman/podman.sock:/run/morphogen-socket/docker.sock morphogen:dev
podman exec -it morphogen morphogen person alice   # then open http://127.0.0.1:8470/ui/
podman exec -it morphogen morphogen login          # Claude Code's sign-in inside the container, once
podman exec -it morphogen morphogen claude interviewer
```

Or on the machine itself:

```sh
python3 morphogen/deploy/local.py up             # Postgres in Docker, the record, the services, the compose runner, the UI
python3 morphogen/deploy/local.py person alice   # you, as a person who reviews; then open http://127.0.0.1:8470/ui/
```

`morphogen/deploy/LOCAL.md` covers both: describing a system with an agent (Claude Code), approving its compose
file in the UI, watching Morphogen start it, and what each way trusts.

## Repository map

```
kernel/        the knowledge kernel (becomes its own repository)
  contract/      the guarantees as executable cases; run.sh, mutants.py
  blueprint/     the kernel's slots and default providers
  schemas/       wire formats: change set, module manifest
  src/kk/        slot interfaces and the provider library (connect, run, submit, follow, ...)
  providers/     default providers: record-postgres, validator-shacl, belief, recall, kernel-mcp, ...
  packs/         vocabulary packs (PROV, SOSA, ORG, DQV, TOSCA mirror, ...)
  evals/         SciFact, LongMemEval, self-model
morphogen/     the distribution
  distribution.yaml  kernel slots used, application slots declared, providers chosen
  modules/       providers for Morphogen's slots (observer, analyser, planner, actuator, verifier, ...)
  contract/      case sets for Morphogen's slots
  intent/        desired state; written only by the intent actuator after approval
  deploy/        the reconciler and the compose runner
  ui/            the review and loop UI
  evals/         G2 runs, RCAEval, design interview, self-model
docs/          rebuild-5.md (plan), decisions.md, LESSONS.md, DEVELOPING.md
```

## Documentation

- `docs/DEVELOPING.md`: setting up, the concepts, writing a provider, testing, the workflow
- `docs/rebuild-5.md`: what this rebuild keeps and changes, the gates, the task list
- `docs/decisions.md`: this rebuild's decisions (R5-xx); rebuild 4's D-01 to D-93 stay settled unless superseded
- `docs/LESSONS.md`: traps earlier rebuilds hit with Postgres, MCP, Docker and evals
- `kernel/contract/invariants.yaml`: the guarantees as named cases
- `CLAUDE.md`: the working rules for agents in this repository
