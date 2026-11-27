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

## Run the check

```sh
uv run --with jsonschema==4.26.0 --with pyyaml python -I demos/research-loop/check.py --metasoar /path/to/MetaSoar
```

Without `--metasoar`, the quotes are not checked and everything else is. The catalog also loads with Morphogen's own
reader (`morphogen.backstage`). Its only cell is the `metasoar` System, as structure: options and roles are never
cells.
