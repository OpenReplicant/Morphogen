# Changelog

Releases are tagged `morphogen--v<version>`, the form Claude Code resolves
plugin dependency ranges against. Before 1.0, a minor version can break the
contract in `docs/distributions.md`; a patch version cannot.

## Unreleased

Breaks the 0.2 contract, so it ships as 0.3.0.

- One store through SQLAlchemy Core (2.0.51, MIT): SQLite by default, one file
  in git's own directory, and any SQLAlchemy database by `database.url` (with
  `schema` and `options` for `create_engine`; only SQLite is tested). A list
  write and its change record commit in one transaction, and a log's `seq` is
  its key, so two sessions writing at once cannot fork a chain (the files
  backend could). On SQLite, triggers refuse edits to the logs.
- Removed: the files and postgres backends (a 0.2 project's JSONL lists and
  logs are imported once, keeping their hashes), the `labels` layout, the
  `nodes` view, `pggraph_sql()` (graph and vector extensions are a
  distribution's choice), the `postgres` extra and pg8000, the Postgres tests
  and CI job, and the `backends` and `evidence_path` config keys (`database`
  instead).
- `lists_export` publishes a map as JSONL for others to mount; mounted maps
  default to the `map/` directory.
- The self-map names Morphogen's knowledge base as a system, `knowledge`, with
  five slots: structure, evidence, history, decisions and recall (replacing
  `morphogen/list-store` and `morphogen/evidence-log`), and its roles as slots
  of `morphogen`: orchestrator, explorer, worker, reviewer, judge and
  operator, each saying what it may write. `ports.py` is brought up to date as
  those slots' interfaces (`ListStore`, `Log`).
- The reviewer also checks changes to a map's slots and requirements before
  they are adopted (map skill step 5; evolve step 10).
- Removed, as outside the base's scope: patterns (`pattern: true`, the
  `realizes` field; they belong in a pattern library mounted as a map), the
  `edges` table and SQL `follow` (the walk is in Python; maps are small), and
  the `catalog` and `meta` tables (`catalogs.yaml` is the source).
- The session hook reads the database read-only with the standard library
  instead of JSONL files, so it no longer misses the journal on another backend.
- Documents (`morphogen.yaml`, `target.yaml`, `catalogs.yaml`, strategy cards) are read
  through one loader, `documents.py`, with a pydantic schema each. A bad document
  is refused with the file and every problem named, instead of failing later or
  being skipped; unknown keys are kept. Replaces seven separate loaders.
  `pydantic` is now a direct dependency (it already came with `mcp`), pinned to
  2.13.4.
- One append-only, hash-chained log mechanism under three logs: `evidence`,
  `changes` (new: every write to the lists, with hashes before and after, the
  entry, who and why) and `journal` (now a log behind the port, not a
  Markdown file). On Postgres, the logs are trigger-guarded tables, and a list
  write commits together with its change record. `lists_put` takes a
  `reason`; `lists_history` reads the change log. The map's history no longer
  depends on git.
- Requirements carry reasons (`because`), and `maps`/`doctor` report
  capability gaps, overhead and unexplained requirements. The evolve skill
  treats a gap as a located gap.
- The core storage requirements are stated so files can always meet them;
  anything more is an optional capability with a flag.

- Capabilities and patterns: slots can `require` capabilities and components
  `provide` them; `catalog_search(slot=...)` ranks fillers by coverage, then
  by fewest extra capabilities. Systems marked `pattern: true` are
  architectures without fillers; `realizes` (a reference field) links a
  system or slot to the pattern it implements, across maps. The self-map's
  storage slots and both backends carry this data. The map skill records it,
  and separates the general method from domain ontologies and integrations.

- A `postgres` backend (optional extra; pg8000, BSD-3-Clause, pinned with its
  dependencies to releases at least four months old). Lists in either of two
  layouts, `tables` (a table per list, a `nodes` view) or `labels` (one
  `nodes` table labelled by list, a view per list); an `edges` table of every
  reference, kept in step with each write; `follow` as a recursive query; a
  `catalog` table mirroring `catalogs.yaml`; an evidence table whose rows a
  trigger refuses to change, so append-only is enforced. The conformance
  tests run against every backend, and the whole suite passes on Postgres
  (`MORPHOGEN_TEST_BACKEND=postgres`).
- `pggraph_sql()` on the postgres backend: the statements that register the
  map with pgGraph (`tables` layout), per its API reference.

- `probe`: a practice run on a candidate under the judge's rules, returning
  per-case results (expected and actual output where they differ) and quick
  metrics. Recorded as evidence of kind `probe`, never a verdict; it does not
  count as a trial (`budget.probes_per_day` caps it).
- Strategy cards `reflect` (learn from failing cases; after GEPA, ProTeGi,
  PromptWizard, meta-prompting) and `tune` (search a component's settings;
  after random and Bayesian search). The methods, not their code.
- An optional `morphogen/model-gateway` slot in the self-map, empty by
  default, and an `llm_gateways` catalog section with Bifrost recommended
  (#43).
- `docs/related-work.md`: Future AGI.

## 0.2.0 (2026-11-03)

The first release that distributions can depend on.

### Distributions
- `docs/distributions.md`: how to build a plugin on Morphogen, its extension
  points, and the contract the base keeps stable (tools and parameters, list
  format, `target.yaml`, strategy cards, evidence records, config).
  `DistributionContract` tests check it.
- `catalog_search` also searches mounted maps.

### Maps
- Several maps (#42): `morphogen.yaml` can mount other maps read-only, pinned
  to a git commit. Qualified ids (`homelab:comp/gpu-box`) refer across maps;
  `follow` crosses them; entries from another map are marked `_trust: stated`.
  The `maps` tool, `doctor` and the admin report list mounted maps and broken
  references.
- The map skill maps anything (code, services, machines, business processes,
  teams, research) as a way of understanding it, starting from its purpose and
  reporting how each claim is known (#40). New map interfaces `observed` and
  `none`.
- The seeded self-map has four systems: `morphogen`, `admin-ui`,
  `claude-code`, `host` (#38, #40). The test checks the core systems are
  present, not that nothing else is (#41).

### Judge
- Closed four cheats that passed under `sandbox: none` (#39): environment
  sniffing and swapping the benchmark's input (timed runs now check their own
  output against the base's), shadowing a harness module with a package (now
  refused), and caching results on disk (a fresh seed every round; a private
  `TMPDIR` and `HOME` per run without a container).
- Tied pairs are left out of the sign test; `gain: absolute` and
  `aggregate: mean` for scores that are often 0 or tie (#39).
- Red-team cases for tampering with the observer and promoting self-reported
  telemetry (#36).
- A/A check after these changes: identical code passed 0 of 12 times.

### Admin UI
- The admin UI is a system of slots (#40). `admin_pages` and the standalone
  `morphogen-admin` write a menu and a read-only report (map, evidence chain,
  archive lineage) to `.morphogen/admin/`; `--serve` is a separate,
  read-only, localhost-only server. A catalog of side-car tools (session
  managers, web terminal, web editor, web desktops) that Morphogen never
  installs.

### Runners and install
- The MCP server is declared in `plugin.json` (#38); a repository-root
  `.mcp.json` broke development sessions.
- Docker and Podman runners verified; `MORPHOGEN_TEST_SANDBOX` runs the suites
  in a container; `ContainerGuarantees` checks no network, a read-only tree, a
  memory limit and nothing kept between runs; a `containers` CI job, started
  by hand (#38).

### Docs and evals
- `CLAUDE.md` for developing the plugin; `docs/related-work.md` (#36).
- Eval notes: Sonnet grader, running from a clean copy, results table.

## 0.1.0

Morphogen as a Claude Code plugin: lists, evidence, the judge, strategies,
skills, subagents, hooks, the slow-script sample and the eval suite.
