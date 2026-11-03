# Changelog

Releases are tagged `morphogen--v<version>`, the form Claude Code resolves
plugin dependency ranges against. Before 1.0, a minor version can break the
contract in `docs/distributions.md`; a patch version cannot.

## Unreleased

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
