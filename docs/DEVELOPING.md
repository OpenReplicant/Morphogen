# Developing Morphogen

How to set up a development environment, how the pieces fit, how to add or change a provider, and how a
change gets merged. The working rules agents follow are in `CLAUDE.md`. Traps earlier rebuilds hit are in
`docs/LESSONS.md`; read it before touching Postgres, MCP, Docker or evals.

## 1. Set up

### What you need

| Tool | Version | Used by |
| --- | --- | --- |
| Postgres | 16+ (pgvector optional) | everything; two clusters for the full suite |
| Python | 3.12+ | providers, tests, evals |
| nftables (`nft`) | any | confining model-written code (module tests) |
| gitleaks | 8.30.1, checked by sha256 | the intake filter |
| Docker | any recent | gate G3 (`test_g3.py`, `test_compose.py`) |
| Node + Playwright | Playwright 1.56.1 with Chromium | the UI test |

The kernel's conformance suite and the provider tests need only Postgres and Python. The rest is for the
Morphogen module suite.

### Postgres

The cluster must ask every login for its password (`scram-sha-256`, never `trust`). The sandbox, builder and
reconciler refuse to start model-written code against a cluster that lets anyone in (R5-24).

```sh
mkdir -p /var/tmp/kpg && chown postgres /var/tmp/kpg
(umask 077; openssl rand -hex 24 > ~/.kk-pgpw)          # the superuser's password: yours alone
install -o postgres -m 600 ~/.kk-pgpw /var/tmp/kpg-pw
su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /var/tmp/kpg/data -A scram-sha-256 -U postgres --pwfile=/var/tmp/kpg-pw"
rm /var/tmp/kpg-pw
su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/tmp/kpg/data -o '-p 5433 -k /var/tmp/kpg' -l /var/tmp/kpg/log start"
export PGHOST=/var/tmp/kpg PGPORT=5433 PGUSER=postgres PGPASSWORD=$(cat ~/.kk-pgpw)
```

The sandbox measures candidate providers on a second cluster of its own, made the same way on port 5434
(`/var/tmp/kpg-sbx`). Point `KK_SANDBOX_CLUSTER` at it:

```sh
export KK_SANDBOX_CLUSTER="host=/var/tmp/kpg-sbx port=5434 user=postgres password=$(cat ~/.kk-pgpw-sbx)"
```

Never write a superuser's password into the repository, or anywhere a run user can read. Confined code reads
the checkout.

### Python

```sh
python3 -m venv /var/tmp/kk-venv
/var/tmp/kk-venv/bin/pip install -r kernel/contract/requirements.txt -r kernel/providers/kernel-mcp/requirements.txt \
  -r morphogen/modules/observer-otel/requirements.txt -r morphogen/modules/registry-lookup/requirements.txt
export KK_PYTHON=/var/tmp/kk-venv/bin/python PATH=/var/tmp/kk-venv/bin:$PATH
```

Put the virtualenv somewhere the run users can read, not in a private home directory.

### Run users, nftables, gitleaks, Docker, Playwright

Only the module suite needs these.

```sh
# OS users for model-written code, one per concurrent run (uids nothing else uses)
for i in 1 2 3 4; do useradd --uid $((2900 + i)) --no-create-home --shell /usr/sbin/nologin kkrun$i; done
for i in 1 2 3 4; do echo kkrun$i >> /etc/cron.deny; echo kkrun$i >> /etc/at.deny; done
export KK_RUN_AS=kkrun1,kkrun2,kkrun3,kkrun4

apt-get install -y nftables
# gitleaks 8.30.1: download gitleaks_8.30.1_linux_x64.tar.gz from its GitHub release, check sha256
# 551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb, put gitleaks in /usr/local/bin

npm install -g playwright@1.56.1 && npx playwright install --with-deps chromium
export NODE_PATH=$(npm root -g)
```

The module suite runs as root, so it can start code as the run users. `.claude/skills/dev/SKILL.md` has the
same steps for a cloud sandbox, including restarting Postgres and Docker after a container restart.
`.github/workflows/ci.yml` is the reference for what CI installs.

## 2. Concepts

### The record

- **Claim.** One statement: subject, predicate, object (an entity or a value), qualifiers, a scope, an
  evidence type (`deterministic`, `extracted`, `inferred`, `observed`, `testimony`), who it is attributed to,
  and the run that made it. A claim is never deleted. Its status (`normal`, `preferred`, `deprecated`, with a
  reason such as `superseded` or `refuted`) changes by later change sets.
- **Change set.** The only way anything is written: `{idempotency_key, attributed_to, generated_by, target_scope,
  lane?, ops}` (`kernel/schemas/change_set.schema.json`). Ops are `add_entity`, `add_claim`, `add_artifact`,
  `set_status`, `add_belief`, `add_verification`. The validator checks a submitted change set, and the store
  applies it, or holds it for a person when its lane is `review`.
- **Agent and role.** Each provider is an agent (`urn:kk:agent:<name>`) with a Postgres role of its own
  (`kkm_<name>`). A person is an agent of kind `person` with a login of their own (`person_<name>`). Row-level
  security decides what each role reads and writes. Clearance is granted by people.
- **Run.** A `prov:Activity`: which module ran, for which plan step, using which claims. Every change set
  names the run that generated it. Actuators record what they did as runs and never claim the outcome; the
  outcome is observed.
- **Belief.** A score per claim from the belief model (corroboration by independent sources, capped when
  refuted or built on withdrawn premises). The UI and every answer show it.
- **Change feed.** Applied change sets and redactions in commit order, read from a cursor.

### Slots and providers

Every concern is a slot with an interface and a swappable default provider. Nothing has a built-in handler.

- Kernel slots: `kernel/blueprint/slots.yaml`. Interfaces: `kernel/src/kk/interfaces.py`.
- Morphogen's application slots and its choice of providers: `morphogen/distribution.yaml`.
- Each slot names its `contract`: a case set every provider must pass (`kernel/contract/slots/<slot>`,
  `morphogen/contract/slots/<slot>`), or `provider-tests` for Morphogen slots without one yet. Every filled kernel
  slot has a case set (T25): the kernel's blueprint says `cases_required: true`, and the runner refuses
  `provider-tests` there.
- The record store's wire API (the `api` schema, what `kk_agent` may read and call in `kernel`, the change-set
  schema's id) is listed in `kernel/contract/api.yaml` with a version `api.version()` returns; `run.sh` fails when
  the two differ. Removing or changing anything listed is a major version, adding is a minor one.

**The split rule.** Anything another distribution could use lives under `kernel/`. Only Morphogen-specific
parts live under `morphogen/`. `kernel/` never imports or references `morphogen/`, and
`python3 scripts/check_boundary.py` enforces it.

### Hooks

No extension code runs inside the commit.

- **Before** the commit, a provider `listen`s for submitted change sets and acts on them: validators, the
  intake filter, lane routing.
- **After** the commit, a provider `follow`s the change feed and acts on what was applied: belief, truth
  maintenance, the analyser, the planner, the verifier. Whatever it produces re-enters as a new change set.

### The loop, by provider

| Step | Provider | Writes |
| --- | --- | --- |
| Monitor | `observer-otel`, `observer-prometheus` | observations (`sosa:hasSimpleResult`) |
| Analyse | `anomaly` | anomaly annotations, inferred from the observations and limits |
| Plan | `planner` | a plan with a step, a risk class and a prediction (`bbo:maxValue`, part of the plan) |
| Route | `lane-autonomy` | sends plan steps to review; autonomy level × risk class picks the lane |
| Approve | a person, in the UI or through kernel-mcp's `review` | the decision on the change set |
| Execute | `intent-actuator` | a commit to `morphogen/intent/`, and a run naming the step |
| Run | `morphogen/deploy/reconcile.py` | nothing in the record: starts what is committed |
| Verify | `prediction-verifier` | a verdict annotation on the plan: holds, fails, untested |

Self-modification adds `builder` (a build request becomes a candidate provider in `intent/experiments/`)
and `sandbox` (the candidate and the incumbent run the slot's contract, then are measured on a copy of the
record).

## 3. Writing a provider

A provider is a directory under `kernel/providers/` (if any distribution could use it) or
`morphogen/modules/` (if only Morphogen does).

```
my-provider/
  provider.yaml      the manifest
  migration.sql      its role, its login, its agent
  my_provider/       the package; the service is python3 -m my_provider
    __main__.py
  tests/
    test_*.py        its own tests
    mutants.py       deliberately broken copies its tests or contract must catch
```

### The manifest

```yaml
id: urn:kk:provider:anomaly
name: Anomaly detection
version: 0.4.0
license: Apache-2.0
slots: [analyser]
emits: [oa:Annotation, oa:hasTarget, oa:bodyValue, dcterms:type]   # the terms its claims use
consumes: [sosa:hasSimpleResult, sosa:observedProperty,            # the terms it needs another provider to emit
           {term: bbo:maxValue, optional: true, from: people}]     # read when there; people may supply it
origin: where it was ported from, or "new"
requires: Python 3.12+, psycopg
migration: migration.sql
service: python3 -m anomaly          # the reconciler accepts only python3 -m <module>
role: kkm_anomaly                    # its Postgres role
login: kkm_anomaly_login             # a login that may switch only to that role
agent: urn:kk:agent:anomaly
tests: [python3 tests/test_detect.py, python3 tests/test_service.py]
runner: python3 tests/contract.py    # only for a case set without a runner of its own: prints "ok: <case>" per case
entry: my_filter.__main__:filter     # a function-level slot's boundary (the intake filter's proposals)
applies_to: [extracted]              # a verifier: the evidence types or predicates it gives verdicts on
```

`emits` and `consumes` are required (`[]` allowed): they are the provider's dependency lines (R5-47). Terms are
CURIEs (`kk.terms.PREFIXES`) or full IRIs and must be defined by a vocabulary pack or the record's bootstrap. A
selection of providers is closed when every term one of them consumes is emitted by another: `kernel/providers/tests/
test_terms.py` checks the kernel's providers, `morphogen/tests/test_closure.py` Morphogen's default selection. Mark a
need `optional` when people can supply it (through the agent interface or the UI) or the provider works without it. Qualifier keys count as terms (a limit's `sosa:observedProperty`, a setting's `kkt:propertyName`). The lines are
at the level of terms, so a need is only as exact as its term: declare it by a term only its real source emits.
The self-encoder records them as `kk:emits`, `kk:consumes` and `kk:mayConsume`.

Which terms to use (R5-51): a published standard's term wherever one has the concept; a `kk:` term only for what no
standard covers, saying so in its definition. Where two standards name one concept, a mapping joins them (a
`skos:*Match` in `kernel/packs/mappings.ttl`, or an SSSOM set imported through the mapping-set slot, which a person
approves). A reader that should count both asks with `kk.mappings` (or kernel-mcp's `query_claims` with
`follow_mappings`) and cites the mapping claims it followed; until a mapping is approved, it is not followed.

`role:` is what a slot's runner runs the provider's service or command as (through a login of its own that may
switch only to that role), so a kernel provider with a service or command names it too.

### The migration

Run once as a superuser by `install.py`. It creates the role (a member of `kk_agent`), grants it to
`kk_authenticator` (so kernel-mcp can act as it), creates its own login, and adds the agent row as
`kk_owner`. Copy `morphogen/modules/anomaly/migration.sql` and rename.

### The service

Use `kk.lib` (`kernel/src/kk/lib.py`). It only removes boilerplate; the kernel enforces everything.

```python
from kk.lib import connect, follow, run, submit

MODULE = "urn:kk:module:my-provider"
AGENT = "urn:kk:agent:my-provider"

def one_pass(conn):
    with conn.cursor() as cur:
        ...                                          # read api.claims: you see only what your role may read
        with run(cur, MODULE, used=premise_ids) as (run_id, outputs):
            res = submit(cur, {"idempotency_key": f"my:{key}", "attributed_to": AGENT,
                               "target_scope": "urn:kk:scope:default", "ops": ops}, run_id)
            outputs.update(change_set=str(res["id"]))

def main():
    conn = connect("kkm_my_provider")               # DATABASE_URL, then SET ROLE
    follow(conn, one_pass)                          # now, then each time the change feed moves; KK_ONCE=1: one pass
```

A slot's case set runs the service with `KK_ONCE=1` (one pass, then exit), so `follow` must be how it waits.

Rules that keep a provider correct:

- **Idempotency keys.** Key each change set by what it is about (`verdict:<prediction id>`), so a restart
  submits nothing twice.
- **Act once per change.** A watcher that must act on each feed entry once keeps a durable cursor:
  `resume(conn, MODULE)` reads the `feed_seq` its last succeeded run recorded (set `outputs["feed_seq"]` in
  `kk.lib.run`; it goes to the run's own column, apart from `cost` and the other outputs, T25), and `feed_since`
  pages through what came after (R5-34; the anomaly service is the example).
- **Cite what you used.** Inferred claims carry `derived_from` with the claim ids they came from. Extracted
  claims carry the quote and its source.
- **Narrow scopes.** A claim's scope must be at least as restrictive as everything it was made from.
- **No self-verification.** A verifier skips claims attributed to itself, and to the agent whose output it
  checks.
- **Effects are observed.** An actuator records a run naming the plan step, never a claim that it worked.

### Tests and mutants

- Put the provider's own tests in `provider.yaml` `tests`. `kernel/providers/test.py` and
  `morphogen/modules/test.py` run them.
- If its slot has a case set, the provider must pass it: `sh kernel/contract/run.sh` or
  `sh morphogen/contract/run.sh`.
- Add a mutant for each rule a test or case checks. A mutant is a description, a file and one or more exact
  `(old, new)` replacements:

  ```python
  MUTANTS = [
    ("a shared source counts as independent", "belief_corroboration/model.py", [
      ("if a.agent == b.agent or a.sources & b.sources:", "if a.agent == b.agent:")]),
  ]
  ```

  `python3 kernel/contract/mutants.py [provider]` (kernel providers) and `sh morphogen/contract/run.sh --mutants`
  (Morphogen's case sets) apply each mutant in a copy and run the contract; every mutant must fail it. For a
  slot without a case set, the provider's own tests must fail on each mutant instead. A provider with a case
  set marks a mutant its own tests must kill (code the cases do not reach, such as a service's cursor) with a
  fourth item, `"own"`. A green check counts only after it has failed with the logic broken.

### Adding a slot

1. Declare it in `kernel/blueprint/slots.yaml` (a kernel concern) or `morphogen/distribution.yaml`
   (Morphogen's), with its default provider and its `contract:`.
2. Add its interface to `kernel/src/kk/interfaces.py` if it is a kernel slot.
3. Give it a case set (`contract/slots/<slot>/set.yaml`, `cases/*.yaml`, a slot-owned `runner.py`); a kernel slot
   must. The slot owns the runner, so a candidate provider cannot certify itself. A kernel slot's runner builds its
   record with `kernel/contract/slots/harness.py` (a fresh database, the provider's migration, its service run once
   as its own role, refused when that role is a superuser or holds more than an agent's rights) and never imports the
   provider. The harness trusts the provider's code (it runs as the harness's OS user): run a model-written candidate
   confined. Two runs of the same set at once collide on its fixed names.
4. Record the decision in `docs/decisions.md`, checked against rebuild 4's decisions first.

## 4. Testing

| Command | What it checks | Needs |
| --- | --- | --- |
| `sh kernel/contract/run.sh` | the API against `api.yaml`, then each kernel provider against its slots' cases: 66 record, 7 lane policy, 13 validator, 17 belief, 9 intake filter, 8 verifier, 11 truth maintenance, 8 recall, 8 agent interface, 6 vocabulary pack, 7 mapping set, 8 self-encoder, 6 evaluator, 18 gap finder | Postgres |
| `python3 kernel/contract/mutants.py` | every mutant fails the contract | Postgres |
| `python3 kernel/providers/test.py` | each kernel provider's own tests, then the services end to end | Postgres |
| `sh morphogen/contract/run.sh [--mutants]` | Morphogen's slot contracts (analyser, runtime), and the kernel slots its modules fill (lane-autonomy: lane policy) | Postgres for the analyser's service cases |
| `python3 morphogen/modules/test.py` | each module's tests, then the full loop (T5), G2, G3, the design agent, catalog lookup, the UI, the local bring-up and the container image | everything in section 1, as root |
| `python3 scripts/check_boundary.py` | `kernel/` never depends on `morphogen/` | nothing |

The module suite takes several minutes. Pass it the full environment:

```sh
sudo -E env "PATH=$PATH" KK_RUN_AS=kkrun1,kkrun2,kkrun3,kkrun4 KK_REQUIRE_DOCKER=1 \
  KK_SANDBOX_CLUSTER="$KK_SANDBOX_CLUSTER" NODE_PATH="$NODE_PATH" $KK_PYTHON morphogen/modules/test.py
```

Single tests run directly, for example `python3 morphogen/tests/test_ui.py` (`KK_UI_SHOT=file.png` saves a
screenshot of the review lane). Each test creates and drops its own database.

### Evals

Evals are not in CI. Each has a `run.py` with stages (`fetch`, `setup`, then a measuring stage) and keeps its
results in `runs/`:

- `kernel/evals/scifact`: recall.
- `kernel/evals/longmemeval`: recall and answering over long chat histories.
- `kernel/evals/self-model`, `morphogen/evals/self-model`: questions about the system's own structure (G7).
- `morphogen/evals/rcaeval`: root-cause ranking.
- `morphogen/evals/design`: the design interview with Haiku as the interviewer.
- `morphogen/evals/ranking`: does the order the gap finder's questions are asked in matter (simulated interviews over real
  compose files; R5-53).
- `morphogen/evals/g2`: recorded self-modification runs.

Rules:

- Models are OpenRouter `:free` models under 10B parameters, or Haiku sub-agents; never paid models. The
  OpenRouter key goes in `OPENROUTER_API_KEY`.
- Rebuild 4's numbers are the floor. A ported area is not done until it matches them.
- Tune on the train split, report on dev. Keep every run, including failed ones.

## 5. Running it

The quickest ways (`morphogen/deploy/LOCAL.md`): the container image (`morphogen/deploy/container/Containerfile`,
run by `morphogen/deploy/container.py`), or `morphogen/deploy/local.py up` on the machine itself, with Postgres in
Docker or, with `MORPHOGEN_DB=embedded`, from the machine's own binaries. Either does all of the below for you.
By hand:

- **Install into a database:** `python3 morphogen/modules/install.py <db>` installs the kernel, the kernel
  providers Morphogen uses, and every module.
- **Run the services:** `python3 morphogen/deploy/reconcile.py --intent morphogen/intent --env sandbox`
  starts each provider an environment's intent names (`intent/environments/<env>/<provider>.yaml`). It reads
  intent from the commit at HEAD only, so an uncommitted edit runs nothing.
- **The UI:** `morphogen/ui/README.md`. Add a person with `python3 morphogen/ui/people.py add <db> <name>`; the
  password is read from stdin. Then start `morphogen/ui/serve.py`.
- **From an agent:** kernel-mcp (`kernel/providers/kernel-mcp`) serves the record over MCP, over stdio as an
  agent's own login or over HTTP with a bearer token per person.

### Environment variables you will meet

| Variable | Meaning |
| --- | --- |
| `DATABASE_URL` | a provider's connection; `connect(role)` then switches to its role |
| `KK_ROLE` | override the role a service switches to |
| `KK_ONCE` | `1`: a feed consumer's service makes one pass and exits (slot case sets run it so) |
| `KK_PYTHON` | the Python the contract runner and confined runs use |
| `KK_RUN_AS` | OS users for model-written code, comma-separated |
| `KK_SANDBOX_CLUSTER` | the sandbox's own cluster (a superuser's conninfo) |
| `KK_REQUIRE_DOCKER` | `1`: Docker tests fail instead of skipping |
| `KK_LOGIN_PASSWORD` | the password `install.py` gives each module's own login |
| `KK_OTLP_SECRET`, `OTEL_EXPORTER_OTLP_*` | telemetry: per-service tokens and the endpoint |
| `KK_SWEEP_SECONDS` | how often a service re-checks without a feed or notify event |
| `KK_JWT_SECRET`, `KK_LOGIN_URL` | the UI's token secret (32+ characters) and where a person's login connects |
| `KK_RERANK` | `1`: cross-encoder re-ranking in recall (the model must be in `KK_EMBED_CACHE`) |
| `KK_EVAL_CACHE`, `KK_EMBED_CACHE` | where evals keep datasets and models |
| `MORPHOGEN_HOME`, `MORPHOGEN_DB`, `MORPHOGEN_PGDATA`, `MORPHOGEN_COMPOSE`, `MORPHOGEN_UI_HOST` | `local.py`: where an instance lives, `embedded` Postgres and its data, `external` when someone else runs the compose runner, where the UI listens (`KK_UI_HOST` to `serve.py`) |
| `KK_CONTAINER_IMAGE`, `KK_BUILD_CA` | `test_container.py`: an image already built, or a CA bundle to build behind a proxy that re-signs TLS |

Each module's `__main__.py` docstring lists the rest of its settings.

## 6. Workflow

1. Pick the next open task in `docs/rebuild-5.md` ("First tasks"). One task at a time.
2. Write the test first where the task allows it.
3. Implement, then run the checks in section 4 that touch your change. Run the full module suite before a
   PR that changes a module or the kernel. Don't commit while it runs.
4. Run the `invariant-reviewer` agent (`.claude/agents/invariant-reviewer.md`) over the diff and fix what it
   finds.
5. Update `docs/rebuild-5.md` (the task's row) and `docs/decisions.md` (a new R5-xx entry for any design
   choice).
6. Commit and open a PR. CI (`.github/workflows/ci.yml`) runs every check except the evals.

What needs the owner's decision:

- Changes to `kernel/contract/invariants.yaml` and the six invariants.
- Positioning and licences.
- Proposed entries in `docs/decisions.md`.

Recommend one option and keep moving on everything else.

Other rules:

- Pin exact versions, checked by hash or digest, and take the latest release, security fixes included (R5-41).
  Look external tools up rather than relying on memory.
- cognee and Graphiti are baselines to reproduce, never dependencies.
- Port from rebuild 4 (`OpenReplicant/kernel`, read-only) rather than rewriting from memory.
- No redesign of the kernel before gate G1 (contract) passes. No redesign of Morphogen before G2
  (self-modifying) passes. New ideas go into `docs/decisions.md` as proposed entries.

## 7. Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| `connection refused` after a container restart | Postgres stopped: `rm -f /var/tmp/kpg/data/postmaster.pid` and start it again (both clusters) |
| a confined run refuses to start | the cluster trusts some login: every `pg_hba.conf` line must be `scram-sha-256` |
| an edit seems to have no effect | a stale `.pyc` from two same-size edits in one second: delete the `__pycache__` folders |
| a module service starts nothing | the reconciler runs only what is committed at HEAD |
| Docker Hub answers 429 | anonymous pulls are rate-limited: wait and retry |
| OpenRouter answers 401 | the key is not set: export `OPENROUTER_API_KEY` |
| OpenRouter answers 429 | the free model is rate-limited upstream: rerun; `answer` stages ask empty answers again |
| `pkill -f <pattern>` killed your shell | the pattern matched the shell's own command line: kill by PID |

More in `docs/LESSONS.md`.
