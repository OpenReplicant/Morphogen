# Lessons

Traps the earlier rebuilds and this one hit, kept so the next session doesn't relearn them. Facts about external
tools here were checked by experiment, as the decisions they cite say. Rebuild 4's lessons about tools this
rebuild does not use (RuleGo, PostgREST, its `kk` command and Docker stack, Caddy, Apache AGE) stay in
`OpenReplicant/kernel`, `docs/LESSONS.md`.

## External tools, as they actually behave

- **MCP Python SDK 2.3.0**: `MCPServer` (not `FastMCP`); `Context.headers` gives HTTP headers (never
  treat them as identity: forward the bearer and let the store check it); only `ToolError` messages
  reach the client; result fields are snake_case (`is_error`, `structured_content`); handshake
  clients negotiate 2025-11-25, the SDK's latest is 2026-07-28.
- A plain **GET on a streamable-HTTP MCP endpoint opens an SSE stream that never ends**: don't use it
  as a readiness probe (use `curl -m 1` or a health route).
- **gitleaks** v8: `gitleaks dir <path> --redact -f json -r <file> --exit-code 0`; the binary is
  static and can be copied out of its image.
- **RCAEval** main.py at rebuild 4's pin refuses Python 3.13: run it under 3.12. RE2-OB and RE2-TT
  unpack to 21 GB (logs.csv, traces.csv, metrics.csv per case) and filled the session's disk; metrics
  methods read only `simple_metrics.csv` (and `inject_time.txt`), so unpack only those (RE2-TT: 531 MB). A zip unpacked
  onto a full disk leaves a partial dataset that main.py scores without complaint (RE2-TT held 55 of 90 cases,
  as rebuild 4's held 63): count `*/*/simple_metrics.csv` before trusting a number. main.py
  skips a download when the dataset directory exists, so a second cache can symlink `data/`.
- **Podman Quadlet** splits `Environment=`, `Label=` and `Exec=` into words as systemd does, but takes
  `WorkingDir=`, `User=`, `HealthCmd=` and `Entrypoint=` as written, quotes included (`User="1000"` becomes
  `--user "\"1000\""`). Every value goes into a systemd unit, so `%` must be doubled and a line break in any value
  starts a new setting: check every value that reaches a unit, `depends_on` names included (R5-46). The
  `podman quadlet` commands arrived in Podman 5.6 and are not in the remote client; Ubuntu's Podman 4.9 has no
  `NetworkAlias=` or `Entrypoint=`. `/usr/libexec/podman/quadlet -dryrun -user` with `QUADLET_UNIT_DIRS` shows the
  generated `podman run` without systemd.
- Pin exact versions and check each download against its hash (npm tarballs against the registry's integrity
  hash before vendoring). The rule that versions be two weeks old was dropped (R5-41): it kept security fixes out.

## Kernel and design

- `run.plan_step` must reference an existing entity (`kernel.entity`).
- `api.change_sets` has no ops and `api.claims` no references: modules add `security_invoker` views
  in their migrations (`api.validation_queue`, `api.claim_references`); kernel RLS still applies.
- Module, vocabulary and TOSCA node-type typings are **forced into the review lane**: a person
  must approve. Approve by id, not "everything from agent X" (that once approved a test module).
- Watermark polling loses work (a returned-but-lost change set left 600 claims unscored). Prefer
  events and make every consumer able to recover what it missed (the belief service rescans
  unscored claims).
- Views that serve people must run with the **viewer's** token (kernel MCP, the UI), not the module's, or
  the view exceeds the viewer's clearance.
- Single-valued properties are typed `owl:FunctionalProperty` in the packs; a version bump of a pack
  reinstalls all of it (no diffing yet).
- Supersede, don't edit: new value + `set_status deprecated superseded replaced_by`.
- An empty libpq connection string is not "no connection": `psycopg.connect("")` connects with the PG*
  variables (a superuser in the dev sandbox). Check for a missing URL before connecting.
- A URL built from a socket connection (`host=/var/run/postgresql`) fails under peer auth for any other
  role: write TCP addresses into logins other processes will use.
- Claude Code expands `${VAR}` in `.mcp.json` (command, args, env), but its docs do not say a settings
  file's `env` reaches MCP servers; keep secrets in a file the server reads (`KK_LOGIN_FILE`).
- A claim in a scope the validator cannot read is never applied: services need clearance on every scope
  they serve (validator, belief, recall index), granted like anyone's.
- BM25 statistics kept per scope make a small scope's rare words worthless: sum them over the scopes
  the reader may read (row-level security does the filtering).
- Recall quality decides whether the kernel helps at all: with plain full-text search a good model did
  worse with the kernel than alone (SciFact, D-59); with BM25 it did much better (D-60). Measure recall
  before building on it.
- A CURIE in a change set expands only with a prefix the kernel knows (`kernel.prefix`, set in
  `002_bootstrap.sql`: rdf, rdfs, owl, dcterms, prov, oa, kk and a few more); `cito:supports` is refused as
  "not a known term". Pack vocabularies without a registered prefix (`org:`, `bbo:`, ...) go in as full IRIs;
  the MCP read tools expand kk.lib's longer list.
- The kernel expands CURIEs in a claim's predicate and object, but stores **qualifier keys exactly as written**:
  `{"kkt:propertyName": "image"}` is accepted and applied, and then nothing that reads
  `qualifiers->>'https://w3id.org/knowledge-kernel/tosca#propertyName'` finds it. Write qualifier keys as full IRIs
  (the interview skill says so; found by submitting the skill's own example, T13).
- The store refuses a **whole** change set when one op breaks a rule (an `add_verification` on the submitter's own
  claim, invariant 5): every other op in it is lost too, and a service that sends one change set per scope stops
  verifying that scope. Filter what the store would refuse before submitting (verifier-quotes judged its own claims
  until the verifier slot's shared cases caught it, T25).
- `api.record_validation` and the other `update ... where id = ...` functions return nothing, not an error, when row
  security hides the row: a validator without a grant on a scope silently validates nothing there. Check the status
  it returns (T25's case-set harness does).
- An agent cannot see another role's change sets (row-level security): a test that waits for an encoder's change
  sets must read their status as the encoder.
- Postgres roles belong to the cluster, not the database: a module's role existing says nothing about whether this
  record has the module. Ask the record (`kernel.agent`).
- Agent IRIs are one namespace: an agent named like a module takes that module's agent, and the module's install
  keeps the wrong one. Never give an agent a module's name.
- Change-set idempotency keys are global, not per agent: re-running an eval stage as another agent collides.
  Score what is recorded instead of re-submitting.
- A vocabulary pack listed in `packs.yaml` without a file loads no terms: the kernel refused `prov:used` (KK030)
  though PROV-O was "a core pack". The catalog check requires each property to be defined in a pack file or the
  bootstrap migration.
- `kernel.readers_subset` compares scope-grant rows literally, not role membership. Deriving a claim in a private
  scope from one in the default scope (granted to `kk_agent`) needs every reader of the private scope to hold its
  own row on the default scope too (D-90).
- psycopg's `conn.notifies()` generator holds the connection: querying the same connection inside its loop kills
  the worker. Take one notification at a time (`stop_after=1`), let the generator close, then query.
- pySHACL runs a SPARQL-based constraint once per focus node as a query string, and rdflib re-parses it each time
  (70% of validating 1,000 claims). The validator caches prepared queries: 22× faster.
- Rebuild 5's schema files are edited in place until a release (T25 added `kernel.run.outputs` and `feed_seq` and
  changed `api.finish_run`'s arguments). A record built from an older checkout lacks them: rebuild it, or bring
  the change over by hand; there are no migrations between schema versions yet. `kernel/contract/api.py check`
  says when the API a checkout expects differs from api.yaml (R5-43).

## Evals and recall

- A model must never see an eval item's key or path when it names the answer: RCAEval's case paths
  (`RE2-TT/ts-auth-service_cpu/1`) gave Haiku the root cause, scoring 0.99. Give items opaque keys,
  keep the map elsewhere, shuffle (D-65). And clear a benchmark's result folder between runs if its
  scorer reads every file there (RCAEval's `output/results`).
- Tune on SciFact's train split, report on dev: the published comparisons are on dev, and a choice made
  by looking at dev results inflates them. On dev, the prompt that won on train did not pay (D-64).
- A search path must never wait on a model download: harness subprocesses get a stripped environment
  (no proxy CA), and fastembed retries for ~40 s before failing. Queries load the model from the local
  cache only; the worker downloads it (D-61).
- A cross-encoder must read what a document says, not one claim of it: re-ranking SciFact claim by
  claim (a title alone, an abstract alone) lost to no re-ranking (0.719 vs 0.723); per subject on the
  recalled claims gained a little (0.731); per subject on all its text claims gained most (0.747, D-66).
  And hybrid scores are min-max normalised over the candidates, so the order depends on how many are
  recalled: compare runs at the same limit.
- Score fusion: never min-max normalise a list that holds only matches (BM25 hits): its weakest match
  becomes 0, the same as a non-match, and with few hits a relevant claim drops below unrelated ones. Divide
  by the best score instead (D-90). Test recall with three or fewer hits, not only large corpora.
- Free model endpoints are rate-limited upstream per model (429 from a shared pool even with quota
  left); probe a few and record which model answered.
- Check each dataset's licence: 4TU.ResearchData's "General Terms of Use" (e.g. BPI Challenge 2017) are
  non-commercial; BPI Challenge 2019 is CC BY 4.0.

## Tests

- A case set judged only on the provider it was written for can pass vacuously: seed each case so it would fail if
  the behaviour were missing (redact a claim only after it was indexed, or the "redacted" case proves nothing), and
  keep a mutant per case (T25).
- A contract that compares what reached an engine must compare everything that engine acts on: the runtime set's
  first model of a compose file dropped service names and top-level keys, so a provider adding `networks:` would
  have passed (R5-46).
- Gate checks that read a live system must tolerate other modules writing meanwhile: assert "every
  claim older than 10 s has a belief", not "zero unscored right now".
- A green eval proves little until it fails when the logic is broken: mutation-check evals (disable
  SHACL, count copies naively) once when you write them.
- Ask the real runtime, not just unit tests: the UI's check runs in headless Chromium, and the Quadlet units are
  run through Podman's own generator.

## The cloud sandbox (Claude Code on the web)

- The container restarts without warning: Docker and Postgres stop, `/tmp` files survive. Restore
  with the steps in `.claude/skills/dev/SKILL.md` (remove `postmaster.pid`, start both clusters, start
  `dockerd`). After a restart Docker may fail with "timeout waiting for containerd": remove
  `/var/run/docker/containerd/containerd.pid` first.
- Outbound HTTPS goes through a TLS-intercepting proxy: pass its CA into image builds as a build
  secret (`KK_BUILD_CA=/root/.ccr/ca-bundle.crt` for `test_container.py`); never disable TLS checks.
- Docker Hub rate-limits anonymous pulls (429): retry after a pause.
- `pkill -f <pattern>` matches the calling shell's own command line and kills it (exit 144); stop
  processes by `/proc/<pid>/exe` instead. `pgrep -f` has the same trap, and a `readlink` test against
  `/bin/bash` misses `/usr/bin/bash`: match the target's exe (`*python*`) or use `pgrep -x`.
- Never give a compose volume a fixed `name:`: every project then shares it, and one test's `down -v` deletes
  the others' data.
- `docker compose up --wait` returns once a container has started, before its server listens: wait for the
  service to answer.
- A free-port probe must close its socket before the port is handed to a server (or the server cannot
  bind and the client sees "connection refused").
- gitleaks v8.30.1 scans on one core, whatever the number of files, and a 728 MB file took 13 min.
  The intake filter splits large files into overlapping byte chunks and runs one gitleaks per CPU
  (an XES log can be a single line, so line-based chunks don't split it).
- `npm install --no-save A` removes other packages installed with `--no-save`: install the UI test's
  packages in one command.
