# Fernhill: an engagement on a made-up firm

The kit alone (the `map`, `catalog` and `morphogen` skills, Morphogen's CLI and judge; no database, no kernel) on a
small business that does not exist: from its documents and an interview to a report of optimisation opportunities,
each written up as an implementation project. It is the kit's done-when (a made-up firm mapped into entity files,
options catalogued for one role, cells drafted for one opportunity) and a demo of what an engagement delivers.

| Folder | What it is |
| --- | --- |
| [material/](material/) | the firm's material, as a client would hand it over: an overview, the office handbook, the systems list, the quote calculator, the job sheet export (`jobs.csv`, 121 jobs) and an interview with the director. All made up. |
| [making/](making/) | how `jobs.csv` was made (`make_jobs.py`, one seed). It holds the true costs the engagement has to find, so no engagement run sees it. |
| [engagement/](engagement/) | the first run's result, done in a Claude Code session following the skills: the map (`catalog-info.yaml`, `catalog/`), the baselines (`analysis/`), the quote calculator as a judged cell (`cells/quote/`), four options for job scheduling (`catalog/scheduling.yaml`) and [the report](engagement/report.md). |
| `prompt.md`, `run.sh`, `check.py` | the engagement unattended: a fresh project from `material/`, Claude Code with only the plugin, then the checks of its result |
| [runs/](runs/) | unattended runs: each one's report and `check.py` output |

## The first run (2026-11-24)

- **Mapped:** the firm as a System, 5 teams, 6 process steps, its tools and 2 roles; 40 evidence quotes, all found
  on the lines they cite (`check.py`).
- **Judged:** the quote calculator, as code with its six cost constants free within bounds and the margin held
  fixed. Held-out cost error 12.4% to 3.4% after `tune` (40 trials), **pass**, 7 runs, sign test p = 0.008, in
  Podman.
- **Catalogued:** Fergus, Tradify, ServiceM8 and shared Google calendars for job scheduling, each fact quoted from
  the vendor's own page; none measured (a trial needs accounts, the operator's call).
- **Report:** four projects: the calculator (about £53,000 a year of margin), quotes in three days, a schedule the
  fitters can see, fewer remakes.

## The unattended run (2026-11-24, sonnet)

`run.sh`, no help: all eight checks pass ([check.txt](runs/2026-11-24-sonnet/check.txt)); 29 evidence quotes, all
found. It mapped the firm, drafted its own quote cell (hours per cabinet split by range), tuned it to held-out
error 15.0% to 4.5% (pass) by moving fixed hours per job from 16 to 50, catalogued Tradify, ServiceM8, Powered Now
and Jobber, and wrote [a report](runs/2026-11-24-sonnet/report.md) of five projects. It said itself that 50 is the
top of the range it allowed, standing in for under-counted hours per cabinet.

## What the runs found in the kit, for issues

1. **A plugin update did not happen.** #102 and #103 changed the plugin but not its version (0.8.0), so
   `claude plugin update` reported "already at the latest version" and kept code from before them; the old code
   read only `morphogen.yaml`. Fixed here: 0.9.0. A version bump belongs in every pull request that changes the
   plugin.
2. **A cell that cannot pass.** With `max_repeats: 6` a deterministic score cannot reach the sign test's bar (the
   best p is 0.0156), so a 9-point gain failed. `status` and `structure_check` could say so before a run.
3. **Org maps are noisy in `status`.** Every process step is listed as a cell, `ready: false`, though none has a
   `run`; structure-only entities could be listed apart.
4. **A tuned value at its bound passes without a word.** The unattended run's pass rests on a setting at the
   top of its range; `tune` could report it, since a value at the bound means the range, not the system, chose it.
5. **The CLI needs a file.** `morphogen structure check` takes the catalog's path, where `status` finds it itself.

Run it again (Python 3.11 or later, Podman, Claude Code signed in):

    demos/fernhill/run.sh /path/to/empty/workdir
    python3 making/make_jobs.py     # only to rebuild material/jobs.csv
