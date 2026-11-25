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
| ingest | documents encoder (Docling, as planned in kernel milestone 6) or a docs MCP server (K3); the source's HTML or LaTeX before its PDF; `verifier-quotes` (kernel D-67) checks each quote and number against its source |
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

## Measures of success

- **Transfer calibration:** of claims predicted to hold here, how many did (Brier score on "the gain held").
- **Yield:** the share of a system's judged improvement that started from the literature, and the cost of each
  verified gain.
- **Honesty:** how often the judge refused a gain that a paper claimed and an implementer reported.
- **Lag:** the time from a paper's publication to a verified adoption.

## Phases

0. **The manual loop recorded as data:** today's session, as claims, conditions, a trial and its outcome.
1. **Ingestion and the claim-condition schema:** papers in, claims with conditions and verified quotes out.
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
