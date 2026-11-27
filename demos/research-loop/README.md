# The research loop, phase 0: one session recorded as data

Phase 0 of [docs/research-loop.md](../../docs/research-loop.md): the loop run once by hand, then written down in the
form the later phases will read. The session is MetaSoar's of 2026-11-25. It read five papers on decision models and
on when to think (MetaSoar's
[`docs/decision-backends.md`](https://github.com/OpenReplicant/MetaSoar/blob/92105f815c6c2691288c162a40f376be4dd564bb/docs/decision-backends.md)).
It then ran the cheapest informative trial, E-04a: MetaSoar's own models read as decision models on JevBench,
against Jev's own predictions
([`trials/decision-readout`](https://github.com/OpenReplicant/MetaSoar/tree/facbe842bcc0778afc2fbe2a9801cd9895d46fab/trials/decision-readout)).
Nothing here runs a model. These are records, and a check that they hold together.

## Layout

| Path | What it holds |
| --- | --- |
| `catalog-info.yaml` | the `metasoar` System, and a `Location` naming the two files below |
| `catalog/map.yaml` | our side: four roles (`decision-backend`, its `readout-calibration`, `think-router`, and `intent-handler` for E-17) and this system's conditions as `Resource`s (LFM3 1.7B Q6_K, Inkling 2 Mini Q4_K, llama.cpp b12627, the GTX 1070 with 8 GB, JevBench at `ed50fe0`, TabMWP at `5a1a522`) |
| `catalog/options.yaml` | 14 options, one `Component` with `spec.lifecycle: candidate` per method: 13 the papers measured, and MetaSoar's own `handler-ladder`; each lists its claim files in `spec.morphogen.evaluation.evidence` |
| `claims/arxiv-*/` | 18 claims from the five papers, one file each ([schemas/evidence-claim.v1.json](../../schemas/evidence-claim.v1.json)), with their conditions and their status for `system:default/metasoar` |
| `claims/e04a/`, `claims/e17/`, `claims/probe/` | 12 of our own observations: six from E-04a's LFM3 run and one from its Inkling 2 Mini run, four from the handler ladder (E-17, E-17b, E-17c, E-17d), one from the probe the note records. Each is a claim with `source.kind: trial` (or `probe`) and `reporting: ours`, which a paper claim's outcome links to |
| `check.py` | validates every claim and every option, and the links between them |
| `catalog/found.yaml`, `research/` | phase 1: the options the research agent found, and its state (below) |

The claims are not `Location` targets, so the judge never reads them (docs/research-loop.md, "Where evidence claims
live").

## What was recorded

| Claim (paper) | Option | Status here | p (transfer) |
| --- | --- | --- | --- |
| `gates-likelihood-readout-27-31b-matches-jev` (2610.00346) | likelihood-readout | **did-not-transfer** for LFM3 1.7B (E-04a; falsifier met); **replicated** for Inkling 2 Mini, about 26B (E-04a; falsifier not met) | none written before |
| `gates-temperature-fixes-calibration` (2610.00346) | temperature-scaling | **replicated** on our setup | none written before |
| `gates-order-effects-untrained` (2610.00346) | likelihood-readout | **replicated** on our setup (a different swap) | none written before |
| `jeval-first-token-readout` (2610.03935) | likelihood-readout | **replicated**, in the qualitative sense only | none written before |
| `gates-embedding-logreg-labelled` (2610.00346) | embedding-logreg | predicted | 0.6 |
| `gates-temperature-option-count` (2610.00346) | temperature-scaling | predicted | 0.7 |
| `jeval-distillation-reasoning-heavy` (2610.03935) | self-distilled-readout | predicted | 0.7 |
| `dart-draft-agreement` (2606.23181) | dart-draft-agreement | predicted | 0.55 |
| `dart-mc-binary-collapses` (2606.23181) | ask-to-think | predicted | 0.7 |
| `zsconf-answer-logprob-auroc` (2605.02241) | answer-logprob-confidence | predicted | 0.6 |
| `zsconf-embedding-router-ood` (2605.02241) | embedding-logreg | predicted | 0.65 |
| `gates-finetuned-classifier-clinc150`, `gates-stated-probabilities-unparseable`, `gates-thresholds-per-model-task`, `gates-cascade-needs-labels`, `jeval-qwen35-4b-thinking`, `jeval-self-distillation-27b`, `lwt-grpo-think-mode` | | untested, each with its reason | |

**The one outcome that bears most:** the gates paper found that two untuned models of 27B and 31B, read by the
likelihood of each option key, matched Jev. Read the same way, LFM3 1.7B untuned reached a pooled accuracy of 0.528
[0.508, 0.547], against Jev 1.13's 0.842 [0.828, 0.857], on the same 3,412 JevBench cases. Its coverage at 5% risk
was 0.09, against Jev's 0.67. After one temperature per slice, its calibration error matched Jev's (0.026 against
0.024), so the claim about temperature scaling did hold here. The gap is accuracy, not calibration. Inkling 2 Mini,
a mixture of experts of about 26B, close to the paper's sizes, reached 0.810 [0.775, 0.843] against Jev's 0.843 on a
sample of 779 cases: 3.3 points below (paired interval [-6.5, -0.3]), with coverage at 5% risk 0.51 against 0.64.
So the claim transferred at the paper's size and not at 1.7B. On those 779 cases d1-2B reached 0.633 and LFM3 0.561.
The claim has one assessment per model, both for `system:default/metasoar`.

**The handler ladder** (MetaSoar E-17 to E-17d, `claims/e17/`) is MetaSoar's own method, with no paper behind it. On
its own 300-case TabMWP stream, templates and handlers answered 58.7% of the last 150 cases at -1.3 points [-3.3,
0.0] against the large model alone. On 150 fresh cases they answered 74.0% but lost 5.3 points [-9.3, -2.0] (E-17b).
Perturbations that keep the answer changed nothing (E-17c). Stricter promotion, a shape gate and a stronger check
removed every error and nearly every cheap answer (8.7%, E-17d).

## How to read it

- **The papers' numbers come through the note.** None of the five papers was quoted, so each paper claim has an
  empty `source.quote` with `quote_status: none`, and carries the note's own sentence in `source.via.quote`. The
  conditions are only what the note states. Anything that matters but is not stated is listed in
  `conditions.unstated`. Phase 1 takes the quotes from the papers themselves.
- **Our own numbers are quoted from MetaSoar at a commit,** and `check.py --metasoar` matches every such quote
  against that file. There are 43 quotes in all, from the claims and from the map's evidence annotations.
- **The predictions are a draft.** The seven probabilities were written by the agent that recorded this session. It
  mapped the note's qualitative status column ("supported", "weak", "brittle out of distribution") onto numbers, and
  each one says so in `prediction.by`. The owner should revise them before any outcome arrives. Each has
  `before_outcome: true`, so it will count towards calibration (the Brier score in docs/research-loop.md). The three
  replicated claims, and the one that did not transfer for LFM3 and was replicated for Inkling, have no prediction. Nobody wrote a probability before E-04a ran,
  so they do not count.
- **"Replicated" here means "held on our setup"** (`comparison: our-setup`). It is a transfer test of the method,
  not a reproduction of the paper. A did-not-transfer is not a refutation either: the model, its precision, the
  engine and the cases all differ.
- **Verdicts.** E-04a is a measurement against a falsifier registered before its outcome (MetaSoar
  `docs/experiments.md`). It is not a candidate the judge decided. So the outcome that did not transfer carries
  `verdict.by: falsifier`, and the others carry `by: none`. Once the readout is tuned as a cell, `by: morphogen` will
  name the judge's verdict.
- **Quotes from 2026-11-26** (the Inkling run and E-17) are from MetaSoar at `22feddc` (its main on 2026-11-27);
  the earlier ones stay at `facbe84` and `92105f8`.

## Phase 1: the first session run by the research agent (2026-11-27)

The `research-loop` skill (`skills/research-loop/SKILL.md`) run once, by Claude Opus 5.5 in Claude Code, with
`morphogen.research` doing the fetching, checking and writing. The map gained two roles from MetaSoar's open
questions (`docs/experiments.md` at `22feddc`: E-04b, E-16, E-17), each with the quoted lines it comes from:
`escalation-gate` and `table-qa`; the handler ladder's papers are claims on the existing `intent-handler` role.
`research/watch.yaml` holds one arXiv topic for each of the three.

- **Watched:** three queries over the last 45 days found 46 papers (`research/seen.jsonl`). Four were read, 37 skipped
  with a reason, and 5 are left `new` for the next session.
- **Read:** Program Distillation (arXiv 2611.19461), Timeout Cascades (2611.24324), TableRouter (2611.32006) and
  TableRoute (2611.25853), all from their arXiv HTML.
- **Cataloged:** 10 claims in `claims/arxiv-2611.*/`, each with a verbatim quote matched against the paper's text
  (`quote_status: checked`, and `quote_location` naming the HTML element), and 6 options in `catalog/found.yaml`.
  The drafts the claims came from are in `research/drafts/`. On the first run the checker refused 4 claims (YAML
  values with commas the draft had not quoted); they were fixed in the drafts and run again, and the repeat runs
  refused every claim already held as a duplicate.
- **Predicted and ranked** (`research/queue.json`: bits of information in the outcome over the trial's hours):

| Claim | Option | Role | p (transfer) | Cost (h) | Score |
| --- | --- | --- | --- | --- | --- |
| `pd-program-beats-ppo` | program-distillation | intent-handler | 0.35 | 1 | 0.93 |
| `pd-first-breakthrough-share` | program-distillation | intent-handler | 0.6 | 2 | 0.49 |
| `tableroute-oracle-route-complementarity` | capability-aware-table-routing | table-qa | 0.6 | 2 | 0.49 |
| `timeout-cascade-near-oracle-router` | timeout-cascade | escalation-gate | 0.65 | 3 | 0.31 |
| `tableroute-computational-support` | computed-table-statistics | table-qa | 0.5 | 4 | 0.25 |
| `tablerouter-statistics-double-accuracy` | computed-table-statistics | table-qa | 0.55 | 4 | 0.25 |
| `pd-reset-swarm-more-effort` | fresh-context-restarts | intent-handler | 0.45 | 6 | 0.17 |
| `timeout-cascade-gpu-hours` | timeout-cascade | escalation-gate | 0.3 | 8 | 0.11 |
| `tableroute-wikitq-gain` | capability-aware-table-routing | table-qa | 0.25 | 16 | 0.05 |
| `tablerouter-post-freeze-bird` | query-aware-table-evidence | table-qa | 0.2 | 20 | 0.04 |

The first row is cheap because its trial is E-18, which is already running: only recording its outcome against the
claim remains. The two after it are re-analyses of E-18's logs. The phase-0 claims have no `trial` yet, so they are
in the queue without a score. All predictions are the agent's draft (`prediction.by` says so), written before any
outcome; the owner should revise them before a trial lands.
- **Steering:** no issue with a `research:*` label existed, so `research/steering.jsonl` is empty.

### Files a website reads

All paths are under `demos/research-loop/`. Everything is a static file; no server is needed.

| File | Format | What it holds |
| --- | --- | --- |
| `research/index.json` | JSON: `{system, claims: [{name, file, about, role, source: {kind, id, title, url}, statement, status, p_transfer}], seen, steering}` | every claim, phase 0's and phase 1's, with the path of its file: the list a static site cannot get by listing a folder |
| `claims/**/NAME.yaml` | YAML, one `EvidenceClaim` (`schemas/evidence-claim.v1.json`) | the claim in full: source, quote, conditions, prediction, trial |
| `research/queue.json` | JSON: `{system, date, how, queue: [{claim, file, role, about, p_transfer, information_bits, cost_hours, plan, prioritised_by, rejected_by, disputed_by, score, currency, cost_money, pledged, received, funded_fraction, funding_source, ready, reason}]}`, best first (funded and `ready` first) | what to test next |
| `research/funding.yaml` (optional) | YAML: `{currency, rate_per_hour, funds: {claim id: {pledged, received, source}}}` | money earmarked for a test; `rank` multiplies the score by 1 + 3 x the fraction funded and marks a fully paid claim `ready` (docs/research-loop.md, Funding). The example is illustrative: no money has been received |
| `research/seen.jsonl` | JSON lines: `{id, version, title, abstract, published, category, topics, roles, status, reason, claims}` | every paper the watch returned, and what became of it |
| `research/steering.jsonl` | JSON lines: `{issue, url, kind, target, title, text, author, association, applied, why, recorded}` | every steering issue recorded |
| `research/watch.yaml` | YAML: `{system, conditions, topics: [{name, question, roles, terms, categories}]}` | what the agent watches, and why |
| `catalog/map.yaml`, `catalog/found.yaml` | Backstage entities | the roles (`spec.type: role`) and the options (`spec.lifecycle: candidate`) claims point at |

`morphogen.research rank` rewrites `index.json` and `queue.json` from the claims, so they never disagree with them.
For the claim site (`site/config.toml`): `sources.claims` stays `demos/research-loop/claims` (the agent writes
there, in `claims/arxiv-ID/`), and `sources.catalog` needs `demos/research-loop/catalog/found.yaml` added beside
`map.yaml` and `options.yaml`, since the options the agent finds are written there.
Steering links are described in `docs/research-loop.md`, "Phase 1: running it".

### Run it

```sh
export MORPHOGEN_RESEARCH_CACHE=~/.cache/morphogen-research   # papers stay here, outside the repository
uv run python -I -m morphogen.research check demos/research-loop --fetch   # re-fetches the four papers, re-checks the quotes
uv run python -I -m morphogen.research rank demos/research-loop
```

## Run the check

```sh
uv run --with jsonschema==4.26.0 --with pyyaml python -I demos/research-loop/check.py --metasoar /path/to/MetaSoar
```

Without `--metasoar`, the quotes are not checked and everything else is. The catalog also loads with Morphogen's own
reader (`morphogen.backstage`). Its only cell is the `metasoar` System, as structure: options and roles are never
cells.
