# The research site

A static site for the research loop ([docs/research-loop.md](../docs/research-loop.md)): the claims the research
agent has catalogued, their status for this system, its transfer predictions against outcomes, and the roles it
watches for, with a page for every claim, paper, trial, model, option and role and the links between them. Built
with [Astro](https://astro.build) 7 into plain HTML in `_build/`; the interactive parts use
[Alpine.js](https://alpinejs.dev)'s CSP build, served from the site itself. No server, no database, no tracking,
nothing loaded from another host.

## Build and preview

Needs Node 22.23.4 or later (the workflow uses 24.5.0).

```sh
cd site
npm ci                      # the exact versions in package-lock.json
npm run dev                 # http://localhost:4321/index.html, rebuilt as you edit (YAML too, on reload)
npm run build               # writes _build/
npm run preview             # serves _build/
npm test                    # the data layer's unit tests (node --test)
cd .. && MORPHOGEN_SITE_TESTS=1 uv run python -m unittest tests.test_site -v   # builds and checks real and hostile input
```

`SITE_CONFIG`, `SITE_ROOT`, `SITE_CONTENT` and `SITE_OUT` point a build at another config, checkout, content folder or
output directory (the tests use them). The scripts set `ASTRO_TELEMETRY_DISABLED=1`. Without `npm ci` in `site/`,
`tests/test_site.py` is skipped (and fails instead when `MORPHOGEN_SITE_TESTS=1`).

## Adding a page: drop Markdown into `content/`

Every `.md` file under `site/content/` becomes a page with the shared layout: `content/how.md` is `how.html`,
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

`config.toml` points at [demos/research-loop](../demos/research-loop): the claims under `claims/` (searched
recursively), the map, `options.yaml` and the agent's `found.yaml` (a missing catalog file is skipped), and the
agent's own files in `research/`: `queue.json`, `watch.yaml`, `seen.jsonl`, and `index.json`, which the build checks
against the claim files. `src/lib/data.mjs` reads them all, validates every claim against
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
| `queue.html` | next to test: `queue.json`, best first, with plan, cost, score, steering, and buttons to prioritise or reject |
| `predictions.html` | predictions waiting for a trial, and a calibration chart with the Brier score once predictions written before an outcome have one |
| `roles.html` | what the agent watches (`watch.yaml`, `seen.jsonl`), the roles, the options for each, and this system's conditions |
| `map.html` | the relations graph, laid out at build time (`src/lib/layout.mjs`); a static SVG of links, with highlighting and filters in Alpine |
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
`src/lib/steer.mjs`. The labels in `config.toml` are the fallback. Text from papers never goes into an issue body,
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
Pages. It runs only when started by hand until its `push` trigger is uncommented, and it needs Pages set to "GitHub
Actions" in the repository's settings. Links are relative, so the site works at `https://<owner>.github.io/Morphogen/`
or on a custom domain.
