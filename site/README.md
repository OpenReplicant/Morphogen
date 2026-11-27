# The research site

A static site for the research loop ([docs/research-loop.md](../docs/research-loop.md)): the claims the research
agent has catalogued, their status for this system, its transfer predictions against outcomes, and the roles it
watches for. `build.py` reads the files named in `config.toml` (EvidenceClaim files,
[schemas/evidence-claim.v1.json](../schemas/evidence-claim.v1.json); the map and options as Backstage entity files)
and writes plain HTML into `_build/`. No server, no database, no tracking, nothing loaded from another host.

`config.toml` points at [demos/research-loop](../demos/research-loop): the claims under `claims/` (searched
recursively, so `claims/arxiv-ID/` is found), the map, `options.yaml` and the agent's `found.yaml` (a catalog file
that does not exist yet is skipped), and the agent's own files in `research/` (its README, "Files a website reads"):
`queue.json`, `watch.yaml`, `seen.jsonl`, and `index.json`, which the build checks against the claim files.

## Build and preview

```sh
uv run python site/build.py                 # or: python3 site/build.py (needs PyYAML; validates with jsonschema if installed)
python3 -m http.server 8000 -d site/_build  # then open http://localhost:8000
uv run python site/build.py --root ../other-checkout --out /tmp/site   # build another checkout's data
uv run python -m unittest tests.test_site -v
```

Every claim is validated against the schema first; an invalid file stops the build.

## Pages

| Page | What it shows |
| --- | --- |
| `index.html` | the feed, newest first, filtered in the page by search, role, source and status (kept in the address, so a view can be shared); works without JavaScript, unfiltered |
| `claims/<name>.html` | one claim: the quote and whether it was checked, the measure and effect, the conditions and what the source left unstated, the transfer prediction and its reason, the cheapest trial that would settle it (`assessments[].trial`) and its place in the queue, the outcome with its trial and verdict |
| `queue.html` | next to test: the agent's `queue.json`, best first, with its plan, cost, score and any steering, and buttons to prioritise or reject |
| `predictions.html` | predictions waiting for a trial, and a calibration chart with the Brier score once predictions written before an outcome have one |
| `roles.html` | what the agent watches (`watch.yaml`'s topics, and what became of the papers in `seen.jsonl`), the roles in the map, the options catalogued for each, and this system's conditions |
| `how.html` | the loop: watch, read, catalogue, predict, test behind the judge, score the prediction |
| `data/claims.json` | the same records, for other tools |

## Steering

The buttons open a prefilled GitHub new-issue page (title, body, labels); nothing is sent until the person submits
it. Each body ends with a `research-action:` line (`prioritise`, `reject`, `dispute`, `question`, `propose-role`,
`propose-option`), with `research-claim:` and `claim-file:` for a claim and `role:` for an option proposed for a
role; the agent reads those lines first (`morphogen/research.py`, `parse_issue`). The labels in `config.toml` are
the fallback: `research:prioritise`, `research:reject`, and `research:question` for the rest. GitHub applies labels
from a link only for people who can triage the repository. Text from papers never goes into an issue body, since it is rendered as Markdown.

## Safety

Claim text comes from papers. Every string from a file is HTML-escaped where it is written, a link from a file is
written only if it is http or https, and each page sets a content security policy that allows only its own
scripts and styles. `tests/test_site.py` builds a claim full of markup and a `javascript:` link and checks that
none of it comes through.

## Deploying

`.github/workflows/site.yml` tests, builds and deploys `_build/` to GitHub Pages. It runs only when started by hand
until its `push` trigger is uncommented, and it needs Pages set to "GitHub Actions" in the repository's settings.
Links are relative, so the site works at `https://<owner>.github.io/Morphogen/` or on a custom domain.
