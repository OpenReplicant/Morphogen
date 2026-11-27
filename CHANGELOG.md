# Changelog

## 0.10.0 (draft, not tagged)

The first public release of rebuild 7: the judge, the kit around it, and the GitHub judge that reads the catalog.

**The judge.** Scores a candidate commit against a base by the base's rules: measurement outside the candidate,
paired rounds with a sign test (A/A: identical code passed 0 of 12), held-out answers given only to the base's
scorer, default deny on what a cell may change, neighbours' interface tests and the system guard. Every verdict goes
into a hash-chained evidence log. The red team holds 61 known cheats, and each must keep failing.

**Ways in.**
- `morphogen judge`, `change`, `measure`, `tune`, `status` on the command line, and an MCP server with 13 tools.
- `morphogen request`: one document in, one verdict out (#78), for a system outside this repository.
- `morphogen intake`: the judge held by another Unix user, so the author cannot read the answers (#83).
- `morphogen pr` and `.github/workflows/judge.yml`: a pull request judged on GitHub Actions by the catalog on main
  (#106). It ran live for the first time on 2026-11-27, in a throwaway pull request on a fixture catalog: an honest
  change passed and a widened `change` was refused (#107).

**The kit.** The map and the catalog are Backstage entity files (`catalog-info.yaml` and its Location targets), with
`spec.morphogen` on the entities (#102, #103; schema `schemas/morphogen-spec.v1.json`). Skills: `map`, `catalog`,
`research`, `morphogen`; agents `worker` and `reviewer`. Optimizers: grid, random, hill-climb with restarts,
annealing, Optuna and GEPA (optional extras), and the selector.

**Systems where they run.** Env values from a file outside the commits, services from a fixed image on an internal
network, and model calls counted at a gateway by the operator's meter (#79, #80).

**Demos.** `fernhill` (an engagement on a made-up firm with the kit alone, #104) and `research-loop` (evidence claims
from papers and from MetaSoar's own trials, as data, #105).

**Known limits.** See README, "Limits". In particular: on GitHub the held-out answers share the runner with
candidate code, and only the container keeps them apart. The dogfood caller (`.github/workflows/morphogen.yml`)
still pins the rebuild-8 judge (`b921c9b`).

**Versions.** The Python package and the Claude Code plugin are both 0.10.0. The package was 0.8.0 and the plugin
0.9.0 before.
