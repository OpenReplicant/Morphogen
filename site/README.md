# The Morphogen site

A static site for any system running Morphogen, covering the kit's four verbs: **map** (the system's parts, the
interfaces they provide and consume, their owners and dependencies), **catalog** (the options for each role, side by
side), **research** (the claims the research agent has catalogued from papers, their status for that system, its
transfer predictions against outcomes: [docs/research-loop.md](../docs/research-loop.md)) and **optimise** (the cells
that may change, and the judge's verdict on each change). Every page is built from files; a page whose files are
absent leaves the header, so a research-only site is still a research-only site. There is a page for every claim,
paper, trial, model, option, role, component, interface and owner, and the links between them. Built with [Astro](https://astro.build) 7 into plain HTML; the interactive parts use
[Alpine.js](https://alpinejs.dev)'s CSP build, served from the site itself. No server, no database, no tracking,
nothing loaded from another host. Everything specific to one system (its sources, name, owner, repository, labels,
theme and navigation) comes from a config file; this folder holds only the templates.

## Your own site

```sh
uv run morphogen site init ROOT              # writes ROOT/site.toml and ROOT/site/about.md
uv run morphogen site build --config ROOT/site.toml --out _site [--base /research] [--install]
```

`ROOT` is a research project (`catalog-info.yaml`, `catalog/`, `claims/`, `research/`). `init` takes the repository
from the `origin` remote and the System from `catalog-info.yaml` (or `--repo`, `--system`, `--title`, `--owner`) and
never overwrites without `--force`. `build` runs `npm run build` here with these variables, which can also be set by
hand:

| Variable | Meaning | Default |
| --- | --- | --- |
| `MORPHOGEN_SITE_CONFIG` | the config file | `site/config.toml` (Morphogen's own demo) |
| `MORPHOGEN_SITE_OUT` | the folder to write | `site/_build` |
| `MORPHOGEN_SITE_BASE` | the path the site is served under, e.g. `/research`: every link and asset then starts with it | none: links are relative, which works under any path |

To deploy on GitHub Pages, copy [skills/research-loop/research-site.yml](../skills/research-loop/research-site.yml)
to `.github/workflows/` in your repository and follow the steps at its top (set `SITE_CONFIG`, pin `MORPHOGEN_REF`,
set Pages to "GitHub Actions"). The research-loop skill has the same steps ("Set up your research site").

## The config file

TOML; every path is relative to the file. `[site] repo` and `[site] system` are required; everything else has a
default. Unknown label actions or navigation pages, or a theme file that does not exist, stop the build.

```toml
[site]
title = "Grove research"             # header, page titles (default "Research")
description = "One sentence"         # meta description of pages that have none of their own
owner = "The Growers"                # whose research it is, in the footer (default: the repo's owner)
repo = "Growers/grove"               # steering issues open here; claim files are linked here
branch = "main"
system = "system:default/orchard"    # the System each claim's status is shown for (an assessment's `system`)
# repo_dir = ".."                    # the repository root, for claim-file links (default: found from .git)

[sources]
claims = ["claims"]                          # searched recursively for EvidenceClaim files
catalog = ["catalog-info.yaml", "catalog"]   # Backstage entity files or folders of them; a missing one is skipped
# map = ["catalog/map.yaml"]                 # entity files for the map and for the options: the same kind of file as
# options = ["catalog/options.yaml"]         #   `catalog`, read with it, named apart so a config says which is which
# verdicts = "verdicts.json"                 # the judge's log (below); optional
research = "research"                        # queue.json, watch.yaml, seen.jsonl, index.json (each optional)
content = "site"                             # Markdown pages (optional)
# schema = "evidence-claim.v1.json"          # default: Morphogen's schemas/evidence-claim.v1.json

[labels]                                     # per steering action; the body's `research-action:` line comes first
prioritise = ["research:prioritise"]
reject = ["research:reject"]
dispute = ["research:question"]
question = ["research:question"]
propose-role = ["research:question"]
propose-option = ["research:question"]

[theme]
css = "brand/theme.css"     # served as assets/user/theme.css, after style.css: override its custom properties
logo = "brand/logo.svg"     # .svg, .png, .webp or .jpg; in the header and as the icon

[nav]
# The header's pages, in order, from: claims, queue, predictions, roles, map, catalog (once a role or option exists),
# optimise (once there is a cell or a verdict), notes (once a note exists), search; `{ page = "search", text = "Find" }` renames one. Markdown pages with `nav: N` follow. Every page is
# built either way.
pages = ["claims", "queue", "predictions", "roles", "map", "catalog", "optimise", "notes"]
# Other links go in the same list as `{ text, href }`. An absolute http(s) URL or a path starting with `/` is written
# as it is (a URL gets rel="noopener"); anything else is relative to the site and gets the base path from `--base`.
# pages = ["claims", "queue", { text = "Lab", href = "https://example.org/lab" }, { text = "Home", href = "/" }]

[funding]                                    # optional: the "fund this" link on the queue and the claim pages
url_template = "https://example.org/fund/{id}/"   # {id} is the claim's id; an http(s) URL or a /path; no link without it
label = "Fund this"                          # the link's text (default "Fund this")
```

The funding figures themselves (a bar, price, share funded, a "ready" badge and the source) come from `queue.json`
(`research/funding.yaml`, `morphogen.research rank`): a claim whose row has no `cost_money` shows none of it.

### The entity files

The map is Backstage `catalog-info.yaml` files (and the files a `Location` in them names, read relative to the file
that names them). The site reads `System`, `Component`, `API`, `Resource`, `Group` and `User`. A Component with
`spec.type: role` is a role, one with `spec.lifecycle: candidate` an option for the role in its
`spec.morphogen.fills`, any other a component; `providesApis`, `consumesApis`, `dependsOn`, `owner` and `subcomponentOf`
become references, each shown both ways. An owner with no `Group` or `User` file still gets a page. A **cell** is a
component (or the System) with `spec.morphogen.run` (or `tests`), read with the System's `defaults` under it; the
System's `spec.morphogen.autonomy` says whether a pass on its lifecycle may be merged by an agent (default: a person
reviews). An option's `spec.morphogen` fields `parameters` (a JSON Schema), `licence`, `docs.url` and `evaluation`
fill the catalog.

### The verdict log

`[sources] verdicts` names a file made from the judge's evidence log, which lives in git's own directory and is not
committed:

```sh
morphogen evidence --limit 100000 > verdicts.json     # a JSON array; JSON lines work too
```

The page shows each record with `kind: verdict`: the change proposed (commits, settings moved, files), passed or
refused, the measures (base, candidate, gain, interval, sign test) and the reasons rebuilt from the record's outcome
the way the judge words them, and the gate (who may merge). A verdict is listed under the cell it names (`cell`,
`cells` or `subject.system`), and one for a cell the map lacks is listed apart. The evidence chain checks each
record's `prev` and `hash` (SHA-256 of its canonical JSON, over the numbers as the file wrote them); an edited record
is named. The judge's own records carry no signature or transparency-log entry; if a record has a `signature`,
`attestation`, `transparency`, `rekor`, `log_index` or `inclusion_proof` field, it is shown as recorded and not
checked. A file that does not exist is skipped with a warning; one that is not JSON stops the build.

Morphogen's own demo builds from [config.toml](config.toml), which points at [demos/research-loop](../demos/research-loop);
[demos/fernhill/site.toml](../demos/fernhill/site.toml) builds the made-up firm: its map, the options catalogued for
job scheduling, and its one cell. Fernhill has no verdict log (its evidence log was never committed), so Optimise
says so and shows none.

## Working on the templates

Needs Node 22.23.4 or later (the workflows use 24.5.0).

```sh
cd site
npm ci --ignore-scripts     # the exact versions in package-lock.json
npm run dev                 # http://localhost:4321/index.html, rebuilt as you edit (YAML too, on reload)
npm run build               # writes _build/ (or MORPHOGEN_SITE_OUT) from config.toml (or MORPHOGEN_SITE_CONFIG)
npm run preview             # serves _build/
npm test                    # the data layer's unit tests (node --test)
cd .. && MORPHOGEN_SITE_TESTS=1 uv run python -m unittest tests.test_site -v   # builds and checks real and hostile input
```

The scripts set `ASTRO_TELEMETRY_DISABLED=1`. Without `npm ci` in `site/`, `tests/test_site.py` is skipped (and
fails instead when `MORPHOGEN_SITE_TESTS=1`). It builds the demo, a hostile fixture, and a made-up second system
through `morphogen site init` and `morphogen site build --base /lab` (another repository, other labels, a theme and
a shorter header), and checks that every link there resolves under `/lab/`.

## Adding a page: drop Markdown into the content folder

Every `.md` file under the config's `content` folder (`site/content/` for the demo) becomes a page with the shared layout: `content/how.md` is `how.html`,
`content/notes/2026-11-27-inkling.md` is `notes/2026-11-27-inkling.html`. Front matter (checked by
`src/content.config.mjs`; a page that breaks it stops the build):

```yaml
---
title: Inkling 2 Mini was tested against the 27B+ finding   # required
description: One sentence, shown under the title and in search
kind: note            # note (default) or announcement: also listed on notes.html, newest first; page: not listed
date: 2026-11-27
refs:                 # entities the page is about; each one's page links back here
  - resource:inkling-2-mini-q4-k
  - trial:E-04a
  - claim:gates-likelihood-readout-27-31b-matches-jev
  - paper:arXiv:2610.00346
  - role:decision-backend
  - option:likelihood-readout
nav: 50               # optional: put it in the header's navigation, ordered by this number
blocks: [statuses, steering, files]   # optional generated sections after the text
draft: true           # optional: leave it out of the build
---
```

A ref to something that is not on the site stops the build. Links inside the text are relative to the page
(`../claims/<name>.html` from `notes/`). The Markdown is ours, not a paper's, so raw HTML in it is passed through;
the content security policy still blocks any inline script.

## Where the data comes from

The config's sources: the claims (searched recursively), the catalog files (the map, the options and the agent's
`found.yaml`), and the agent's own files in `research`: `queue.json`, `watch.yaml`, `seen.jsonl`, and `index.json`,
which the build checks against the claim files. `src/lib/config.mjs` reads the config; `src/lib/data.mjs` reads them all, validates every claim against
[schemas/evidence-claim.v1.json](../schemas/evidence-claim.v1.json) (Ajv, draft 2020-12; an invalid claim or a name
used twice stops the build), and joins them into one graph: entities, typed references, and the backlinks of each.

| Entity | Page | From |
| --- | --- | --- |
| claim | `claims/<name>.html` | an EvidenceClaim file |
| paper | `papers/<id>.html` | a claim's `source` when it is outside work (`arxiv-2610.00346`) |
| trial | `trials/<id>.html` | a claim's `source` when it is our trial or probe, and every outcome's `trial.id` (`e-04a`) |
| resource | `resources/<name>.html` | a Resource: a model, engine, GPU or dataset |
| option | `options/<name>.html` | a Component with `lifecycle: candidate` |
| role | `roles/<name>.html` | a Component with `type: role` |
| system | `systems/<name>.html` | the System |
| component | `components/<name>.html` | any other Component |
| api | `apis/<name>.html` | an API: who provides and consumes it, its tests |
| group | `owners/<name>.html` | a Group or User, or a name given as an owner |
| page | `<path>.html` | a Markdown file in `content/` |

References: a claim's `about` (option), `role`, `source` (paper or trial), `conditions.*.ref` (measured on),
`assessments[].against` (assessed on, with the status), `outcome.trial` (tested in), `outcome.observed` and
`see_also` (claims); an option's `fills`; a role's `subcomponentOf`; `spec.system`; a page's `refs`. Every entity page
ends with all of them, both ways ("Links to", "Linked from"), and adds its own views: a claim's "tested on" table
(model by result); a model's claims tested with it and each result, its trials and our measurements on it; a trial's
outcomes and the models it ran, and related trials (E-17, E-17b...); a paper's claims; a role's options, open
questions (`watch.yaml`), what has been tested and what is next in the queue.

## Pages

| Page | What it shows |
| --- | --- |
| `index.html` | the feed, newest first, filtered in the page by search, role, source and status (kept in the address); without JavaScript, unfiltered |
| `queue.html` | next to test: `queue.json`, best first, with plan, cost, score, funding (when there is a `funding.yaml`), steering, and buttons to prioritise or reject |
| `predictions.html` | predictions waiting for a trial, and a calibration chart with the Brier score once predictions written before an outcome have one |
| `roles.html` | what the agent watches (`watch.yaml`, `seen.jsonl`), the roles, the options for each, and this system's conditions |
| `map.html` | the system's graph (parts, interfaces, dependencies; only when the map has any), a table of every part with its owner, interfaces, dependencies and dependents, and the research's relations graph; static SVGs laid out at build time (`src/lib/layout.mjs`), with highlighting and filters in Alpine |
| `catalog.html` | per role: a table comparing its options (interfaces, parameters, licence, docs, measurements, claims), then each option's parameters, measurements and the trade-offs its claims report |
| `optimise.html` | the cells (what may change, the score, what the judge last measured, autonomy), the verdicts on each, and the evidence chain |
| `search.html` | everything by kind; with JavaScript, a search over `data/search.json` (the header's box lands here) |
| `notes.html` | notes and announcements from `content/` |
| `data/claims.json`, `data/graph.json`, `data/search.json` | the records, the whole graph (with the calibration pairs and Brier score), the search index |

## Layout of this folder

`src/layouts/Base.astro` is the frame of every page; `src/pages/<type>/[name].astro` is the layout of one entity type,
written once; `src/components/` holds the shared pieces (status badges, the "tested on" table, the references
panel). `public/assets/` is copied as is: `style.css` (light and dark themes), `theme.js` (applies the chosen theme
before the page paints), `site.js` (the Alpine components). `astro.config.mjs` copies Alpine's CSP build from
`node_modules/@alpinejs/csp` into `public/assets/vendor/` (not committed) on every build and dev start.

## Steering

The buttons open a prefilled GitHub new-issue page (title, body, labels); nothing is sent until the person submits
it. Each body ends with a `research-action:` line (`prioritise`, `reject`, `dispute`, `question`, `propose-role`,
`propose-option`), with `research-claim:`, `claim-file:` and `status:` for a claim and `role:` for an option proposed
for a role; the agent reads those lines first (`morphogen/research.py`, `parse_issue`). They are written by
`src/lib/steer.mjs`. The labels in the config's `[labels]` are the fallback. Text from papers never goes into an issue body,
since it is rendered as Markdown.

## Safety

Claim text comes from papers. Astro escapes every value written into a page (`&`, `<` and `>` in text; `&` and `"`
in a quoted attribute, where `<` cannot open a tag), and no page uses `set:html`. A link from a file is written only
if it is http or https (`safeUrl`). Each page's content security policy allows only its own scripts, styles and
data (`default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'`, no `unsafe-inline` or
`unsafe-eval`): there are no inline scripts or style attributes, and Alpine's CSP build evaluates directives without
`new Function`, from components registered by name with `Alpine.data`. `tests/test_site.py` builds claims full of
markup and a `javascript:` link and checks that none of it comes through.

## Deploying

`.github/workflows/site.yml` installs the locked packages, runs the tests, builds and deploys `_build/` to GitHub
Pages: Morphogen's own demo. It runs only when started by hand until its `push` trigger is uncommented, and it needs
Pages set to "GitHub Actions" in the repository's settings. Links are relative, so the site works at
`https://<owner>.github.io/Morphogen/` or on a custom domain; `MORPHOGEN_SITE_BASE` makes them absolute under a path.
For your own repository, use the template in [skills/research-loop/research-site.yml](../skills/research-loop/research-site.yml).
