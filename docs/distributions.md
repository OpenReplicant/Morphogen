# Building a distribution on Morphogen

A distribution is a Claude Code plugin in its own repository that depends on
Morphogen and adds what one kind of work needs: skills, strategy cards,
catalogs, maps and sample targets for an assistant, a business, games. The
base stays general; a distribution can be public or private, under its own
licence.

The base ships no example distribution, to stay lean; use-case work lives in
the distributions' own repositories.

## Declaring the dependency

In the distribution's `.claude-plugin/plugin.json`:

```json
"dependencies": [
  { "name": "morphogen", "marketplace": "morphogen", "version": "^0.2.0" }
]
```

A distribution hosted in its own marketplace must allow the dependency in its
`marketplace.json`, or Claude Code will not install Morphogen for it:

```json
"allowCrossMarketplaceDependenciesOn": ["morphogen"]
```

The version range resolves against the base's release tags
(`morphogen--v0.2.0`). Test both together without installing anything:

```
claude --plugin-dir path/to/morphogen --plugin-dir path/to/your-distribution
```

## Extension points

| To add | Do this | How the base finds it |
|---|---|---|
| Skills, subagents, hooks | put them in the distribution's own plugin; they are namespaced (`your-dist:skill`) | Claude Code loads them; skills call the base's tools as `mcp__plugin_morphogen_morphogen__<tool>`, allowed by `mcp__plugin_morphogen_morphogen` in `allowed-tools` |
| A map of known systems, types, sources and components | ship JSONL lists in the distribution's repository; the operator mounts them under `maps:` in `morphogen.yaml`, pinned to a commit | read-only, by qualified id (`yourdist:type/nas`); `catalog_search` searches mounted maps |
| Strategy cards | copy them into the project's `strategies/` (a skill can do it from `${CLAUDE_PLUGIN_ROOT}`) | `strategies_list` reads the base's cards and the project's; the project's win on a name clash |
| Catalog sections | add entries to a mounted map, or sections to the project's `catalogs.yaml` | `catalog_search` reads every section of `catalogs.yaml` |
| Sample targets | copy a target directory with its `target.yaml` into the project | `measure` and `judge` take any target path |

Mounting a map and adopting a target are the operator's changes: a skill
should propose them, not make them.

## What a distribution must not do

- Change the judge, its rules, the budgets or the operator's intent; write
  `measured` evidence (only the judge does); or take approvals anywhere other
  than the conversation and pull requests.
- Edit the installed base plugin's directory.
- Write into a mounted map (the base refuses it): a map changes in its own
  project, through its own judge.

Its own hooks and MCP servers run with the user's privileges. List them, with
their permissions and dependencies, in the distribution's map, so operators
can assess it as a source.

## The contract

What the base keeps stable within a major version. Removing or renaming any
of it, or changing its meaning, is a breaking change and needs a new major
version; adding to it is not. Before 1.0, the minor version plays that role:
`^0.2.0` accepts 0.2.x only, and a breaking change ships as 0.3.0.
`DistributionContract` in `server/tests/test_morphogen.py` checks this list.

**MCP tools** (names and parameters):

| Tool | Parameters |
|---|---|
| `doctor`, `init_project`, `maps`, `strategies_list`, `admin_pages` | none |
| `install_sample` | `name`, `dest` |
| `lists_get` | `kind`, `id` |
| `lists_put` | `kind`, `entry` |
| `lists_query` | `kind`, `where`, `follow`, `start`, `hops`, `map` |
| `evidence_query` | `contains`, `by`, `limit` |
| `evidence_note` | `claim`, `source`, `trust` (`inferred` or `stated`), `supports`, `challenges` |
| `catalog_search` | `query`, `limit` |
| `measure` | `target`, `ref` |
| `judge` | `target`, `candidate`, `base`, `labels` (`strategy`, `approach`, `family`, `parent`) |
| `probe` | `target`, `candidate`, `base`, `cases`, `rounds` |
| `strategy` | `target` |
| `archive` | `target`, `limit` |
| `journal_append` | `title`, `gap`, `options`, `choice`, `rung`, `gate`, `commit`, `why` |

**Lists:** the kinds `systems`, `slots`, `types`, `sources`, `components`;
the reference fields (`systems.slots`; `slots.system`, `accepts`,
`filled_by`; `components.type`, `source`, `system`); qualified ids
`map:id`; map interfaces `direct`, `simulated`, `observed`, `none`; the
`_map` and `_trust` annotations on entries from mounted maps.

**`target.yaml`:** `name`, `description`, `interface` (`direct` or
`simulated`) and `simulates`, `harness`, `check`, `equivalence` (`gen`,
`run`, `cases`), `measure` (`run`, `warmup`, `repeats`, `max_repeats`,
`same_output`, `observer` with `run` and `collected`, and `metrics` with
`direction`, `primary`, `min_improvement`, `max_regression`, `gain`,
`aggregate`), `timeout`. Primary metrics are judge metrics (`wall_seconds`,
`cpu_seconds`, `max_rss_kb`) or `observed.*` collected outside.

**Strategy cards:** Markdown with front matter `name`, `description`, `when`
(and optionally `weak_when`), and Parent, Candidates, After and Stop sections.

**Evidence records:** `seq`, `at`, `prev`, `hash`, `claim`, `kind`, `trust`
(`measured`, `simulated`, `stated`, `inferred`), `by`; verdicts also carry
`verdict`, `subject`, `refs` (`base`, `candidate`), `outcome`, `seeds`,
`labels`, `interface`, `sandbox`, `runner`; probes have `kind: probe` and are
never verdicts. A distribution reads evidence; it
writes only through `evidence_note`.

**Config:** `morphogen.yaml` keys `trunk`, `autonomy`, `data_dir`,
`evidence_path`, `strategy`, `strategies`, `backends`, `sandbox`,
`sandbox_image`, `budget`, `targets`, `map_name`, `maps`.

Anything not listed here (internal modules, file layouts under
`.morphogen/`, the admin pages' markup) may change in any release.
