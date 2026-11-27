# The research loop: keeping a system current with the literature, behind the judge

A concept note, 2026-11-25. A proposal, not a plan step. It was written after a session that ran this loop by hand
(MetaSoar `docs/decision-backends.md`), and it is meant to become a research project of its own, worth founding and
funding.

## The problem

A good engineer keeps their systems current by reading their field: a new method, a better default, a model that
now fits on the hardware. Agents that optimise systems mostly do not. They work from what the model already knows
and from the failures they observe, so their improvements are reactive and bounded by the model's training.
Meanwhile the literature produces far more candidate improvements than anyone tests. Most are reported once, on a
setup unlike yours, and their gains are often overstated: meta-analytic effects have run about three times larger
than large preregistered replications (Kvarven et al.), and agents asked to replicate whole papers succeed at a
fraction of them (PaperBench).

## The idea

A background loop in Morphogen's kit that does what that engineer does, steadily and at low priority:

1. **Watch** the literature for what the map cares about: each role's options, and each open question in the
   system's docs. It does not read a general feed.
2. **Catalogue the evidence.** A paper's method becomes an option for a role. Its claims become evidence on that
   option, each with its conditions: model and capability, precision, engine, dataset, number of runs, whether the
   number is self-reported, and where in the paper it came from.
3. **Predict transfer.** Compare a claim's conditions with this system's own (from the map and its observed state)
   to estimate whether the gain carries over, and how much to trust it.
4. **Choose the next trial** by expected gain, times the chance of transfer, divided by its cost. Cheap,
   high-information trials go first.
5. **Implement and judge.** An optimiser or a coding agent turns the method into a candidate change to a cell, using
   the paper's released code where there is some. Morphogen's judge decides on cases the implementer never saw.
6. **Record the outcome against the claim**: replicated, did not transfer, or not testable here. Merged gains
   accumulate behind the ratchet. Transfer outcomes then calibrate step 3, so the loop learns which kinds of claims,
   sources and conditions carry over to systems like this one.

Most papers stop at step 2: a catalogued option with its evidence, ready when someone needs it. The loop's other
output is ideas. A method from one paper applied to a role no paper considered is a hypothesis the catalog can hold
until it is worth a trial.

## Prior work, and what is different

| Work | What it does | What it does not |
| --- | --- | --- |
| **ScholarEvolve** (Yang et al., arXiv 2609.40169, 2026) | the closest: from an agent's failures, searches arXiv, groups papers into mechanism families by topic modelling, implements them as mutations of five harness modules (tools, context, skills, memory, workflows), crosses modules over and selects on a dev set. Qwen3.5-27B on AppWorld from 49.6% to 63.6%; removing research guidance cost points at every step of the ablation; new publication windows kept improving the harness | targets the agent harness only; selection on a dev set, not by a judge the optimiser cannot edit; no persistent evidence base or prediction of transfer; vetting papers and their code for malicious content is not addressed |
| **PaperBench** (OpenAI, ICML 2025) | agents replicate 20 ICML 2024 papers from scratch | shows how hard replication is: the best agent 21% at first, ML PhDs 41.4% on a subset in 48 hours, agents weakest at running code and matching results |
| **AIDE²** (arXiv 2609.26457) | a research agent improves its own research process: seven successive improvements in an 8-day run | draws on the literature only loosely |
| replication and forecasting research | published effects overstated; prediction markets forecast replication with a correlation of 0.62 | not applied to engineering decisions about one's own system |

What is different here:
- **Evidence with conditions, kept.** It sits in a catalog shared across systems and runs, not in a one-off search.
- **Transfer is predicted, then scored.** Each prediction is checked against a judged outcome, so trust in the
  literature becomes something measured and calibrated.
- **A judge the optimiser cannot edit.** Gains accumulate only through Morphogen's ratchet.
- **Any role in the map**, not only an agent's harness: model settings, components, infrastructure, prompts, code.
- **Runs in the background on modest hardware.** It is meant as a standing habit, not a burst of compute.

## How it sits on the kit

| Step | Part |
| --- | --- |
| watch, find | the `research` skill, driven by the map's roles and the docs' open questions |
| ingest | documents encoder (Docling, as planned in kernel milestone 6) or a docs MCP server (K3); the source's HTML or LaTeX before its PDF; `verifier-quotes` (kernel D-67) checks each quote and number against its source; the parser survey is `docs/research-loop-parsers.md` |
| catalogue | options as `Component`s with `spec.lifecycle: candidate`; evidence as claims on them, with conditions |
| our side | the map and its observed state (encoders for running components, model files, hardware, git) |
| predict, schedule | new: a transfer model over claim conditions against ours; a value-of-information queue |
| implement | an optimiser adapter (GEPA for prompts, a coding agent for code), in a sandbox: papers and their code are untrusted input |
| judge | Morphogen's judge, unchanged |
| learn | the evidence log, ingested by the kernel (`encoder-morphogen`, kernel D-99), linked to the claim that motivated the trial |

The new code is the transfer model, the scheduler and the claim-condition schema. Ingestion, cataloguing,
optimising and judging exist or are already planned.

### Where evidence claims live

A claim is a file of its own ([schemas/evidence-claim.v1.json](../schemas/evidence-claim.v1.json), a draft). It is
not part of the option's `spec.morphogen`. Each file is shaped like a Backstage entity of a custom kind
(`apiVersion: morphogen.dev/v1alpha1`, `kind: EvidenceClaim`). It names the option in `spec.about` and the role in
`spec.role`. The option lists its claim files in `spec.morphogen.evaluation.evidence`, as the `catalog` skill already
does for a trial's output. Claim files are never `Location` targets of the judge's catalog. Why:

- **Claims change on a different clock.** A claim's status moves from predicted to replicated each time a trial
  lands, and claims are added as papers are read. Every catalog file is a rule file, read from the base commit, and
  an option rarely changes. Keeping claims out of the catalog keeps the rules stable. Default deny still keeps
  candidates out of them, since a claim file is named in no cell's `change`.
- **`spec.morphogen` is the code's contract.** Its schema matches the fields the judge loads, and a test keeps the
  two equal. Claims would add a nested structure the judge never reads. `evaluation.evidence` already takes a list
  of files.
- **One claim, many systems.** A claim's source, numbers and conditions are the same for every system that reads
  it. Only its status differs, so each system adds an `assessments` entry rather than a copy (phase 5).
- **A trial's own result is a claim too** (`source.kind: trial`, `reporting: ours`). The paper claim it tests links
  to it from `outcome.observed`. A result that bears on several claims is then written down once.

[demos/research-loop](../demos/research-loop/README.md) is phase 0 in this form.

## The first worked example

MetaSoar, 2026-11-25:
- **Sources:** papers on decision models and on when to think (arXiv 2610.00346, 2610.03935, 2606.23181,
  2605.02241).
- **Claims compared with our conditions** in a table, by hand. Our model is LFM3 1.7B Q6_K on llama.cpp; the papers
  measured 14B and up on vLLM.
- **The cheapest informative trial:** E-04a, our model's readout against Jev's own predictions on JevBench cases.
  It is set up as a cell whose prompt and settings an optimiser may change.

Recording that session as data is phase 0.

## Phase 1: running it

Phase 1 is built (2026-11-27): the `research-loop` skill (`skills/research-loop/SKILL.md`) runs one session, and
`morphogen/research.py` does every step that needs no judgement. The first session's output is in
[demos/research-loop](../demos/research-loop/README.md), "Phase 1".

| Step | Who | What it writes |
| --- | --- | --- |
| steer | `research steer ROOT --repo O/R` | `research/steering.jsonl`; a topic in `watch.yaml` per question |
| watch | `research watch ROOT` (arXiv API, one request every 3 s, a generic User-Agent naming the project) | `research/seen.jsonl` |
| triage | the model, then `research triage` | a status and reason per paper in `seen.jsonl` |
| read | `research fetch ROOT ID` (arXiv HTML; the PDF through Docling when there is no HTML and Docling is installed) | the cache, outside the repository |
| extract, predict | the model | `research/drafts/ID.yaml` |
| catalog | `research catalog ROOT DRAFT` (quote found in the text, role on the map, schema, dedupe) | `claims/arxiv-ID/*.yaml`, `catalog/found.yaml` |
| rank | `research rank ROOT` | `research/queue.json`, `research/index.json` |

The schema gained one optional field, `assessments[].trial` (`plan`, `cost_hours`, `needs`, `code`): the cheapest
trial that would settle a claim here and its cost, which the ranking needs. It is backward compatible: every claim
file valid before is valid now (a test checks phase 0's).

**Steering** comes from GitHub issues, which the claim site (`site/`, PR #108) opens with prefilled links. GitHub
applies a link's labels only for people with triage access, so the site also writes lines at the end of the body,
and those come first:

```
Please test this claim sooner.

---
research-action: prioritise
research-claim: timeout-cascade-gpu-hours
claim-file: https://github.com/OpenReplicant/Morphogen/blob/main/demos/research-loop/claims/arxiv-2611.24324/timeout-cascade-gpu-hours.yaml
```

`research-action` is one of `prioritise`, `reject`, `dispute` (the transfer prediction is wrong), `question`,
`propose-role` or `propose-option`. Without that line the kind comes from the labels `research:prioritise`,
`research:reject` and `research:question` (which the site also uses for disputes), or from a title starting
`[research:...]`. The target is `research-claim`, or a `claim:`, `paper:`, `role:` or `option:` line. Effects: a
prioritised claim counts double in the queue, a rejected one leaves it (a rejected paper is not read again), a
disputed one is flagged in the queue (`disputed_by`) for the next session to reassess in a new assessment, and a
question or proposal becomes a watch topic waiting for its terms. Every issue is recorded in `steering.jsonl`; only
those from the repository's owner, members and collaborators (the REST API's `author_association`) are applied, so
a stranger's issue cannot steer the agent.

### Funding

An optional `research/funding.yaml` lets money steer the queue. Keys under `funds` are claim ids (a funded
direction is a claim); `rate_per_hour` turns the trial's `cost_hours` into a price:

```yaml
currency: USD
rate_per_hour: 12
funds:
  pd-program-beats-ppo:
    pledged: 5        # promised, not yet paid
    received: 6       # paid
    source: "GitHub Sponsors, one-time, ref 1234"   # provider and reference only; no names, no emails
```

`rank` computes `funded_fraction = min(1, (pledged + received) / (cost_hours x rate_per_hour))` and multiplies the
claim's score by `1 + 3 x funded_fraction` (unfunded x1, half funded x2.5, fully funded x4), on top of the steering
doubling. A claim is `ready` only when `received` alone covers the price; ready claims sort first in `queue.json`,
whatever their score (a rejected claim is never ready). The queue rows record `currency`, `cost_money`, `pledged`,
`received`, `funded_fraction`, `funding_source` and `ready`. Money is a priority, not a verdict: it does not change a
claim's prediction, and the result is recorded whichever way it falls. Ids that match no claim are ignored. Money
without a `rate_per_hour` is refused.

**To turn it on**, on GitHub (nothing is enabled by this change):

1. Create the three labels: `research:prioritise`, `research:reject`, `research:question`.
2. Add the repository secret `CLAUDE_CODE_OAUTH_TOKEN` (`claude setup-token`; the owner's subscription, no API key).
3. Copy `skills/research-loop/research-session.yml` to `.github/workflows/`, run it once by hand, read the draft pull
   request it opens, and only then uncomment its `schedule`. A pull request opened with the workflow's own token
   does not start other workflows, so the judge's checks run once someone pushes to the branch or re-opens it.

Or, without Actions, a Claude Code scheduled task: `/schedule` with the prompt "In OpenReplicant/Morphogen, read
skills/research-loop/SKILL.md and run one session on demos/research-loop with --repo OpenReplicant/Morphogen; open a
draft pull request into main", weekly. Or by hand, in any harness: ask it to follow the skill.

**On cheap or local models:** steps 3 to 6 are the only ones that need a model, one paper at a time, and the draft
is small. A weaker model will draft weaker claims, but it cannot write a quote that is not in the paper or a file
the schema refuses. Its predictions are its own: `prediction.by` names the model, so calibration can be scored per
model later.

**Left for later phases:** reading the PDF route by default (Docling is used only when installed); a page or bbox
for each quote (arXiv HTML has element ids, recorded in `quote_location`, but no pages); a transfer model learned
from outcomes (phase 2) in place of the model's own `p_transfer`; recording outcomes against claims automatically
when a trial lands; claims from sources other than arXiv; the same claim assessed for several systems (phase 5).

## Measures of success

- **Transfer calibration:** of claims predicted to hold here, how many did (Brier score on "the gain held").
- **Yield:** the share of a system's judged improvement that started from the literature, and the cost of each
  verified gain.
- **Honesty:** how often the judge refused a gain that a paper claimed and an implementer reported.
- **Lag:** the time from a paper's publication to a verified adoption.

## Phases

0. **The manual loop recorded as data:** today's session, as claims, conditions, a trial and its outcome.
1. **Ingestion and the claim-condition schema:** papers in, claims with conditions and verified quotes out. Built: see "Phase 1: running it".
2. **A first transfer model:** heuristics over condition distance, scored against outcomes as they arrive.
3. **The background scheduler:** a standing queue, a budget, and nothing urgent.
4. **Implementation agents in a sandbox,** starting with methods that ship code.
5. **Across systems:** transfer outcomes pooled over every system that uses the kit.

## Risks

- **Implementation fidelity:** a failed replication is ambiguous. Reproduce the paper's own number on its own setup
  before porting.
- **Untrusted input:** papers can carry prompt injections, and their code can be malicious. Read them as data, and
  run their code sandboxed.
- **Weak evidence:** many results are self-reported single runs. The transfer model should learn that discount.
- **Contamination:** benchmarks may be in the models' training data, so held-out cases stay with the judge.
- **Compute:** consumer hardware limits trials to cheap ones first, which is also good research practice.

## Sources

- [ScholarEvolve: Learning from Research: Toward Lifelong Agent Harness Evolution](https://arxiv.org/html/2609.40169)
- [PaperBench: Evaluating AI's Ability to Replicate AI Research](https://arxiv.org/abs/2504.01848)
- [Recursive self-improvement of AI research agents (AIDE²)](https://arxiv.org/html/2609.26457v1)
- [Predicting replicability: survey and prediction-market data](https://pmc.ncbi.nlm.nih.gov/articles/PMC8046229/)
- [The puzzling relationship between multi-laboratory replications and meta-analyses](https://royalsocietypublishing.org/rsos/article/9/2/211499/96580/The-puzzling-relationship-between-multi-laboratory)
