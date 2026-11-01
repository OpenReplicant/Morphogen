# Morphogen, redrawn: an autonomous platform team

Working note from the operator session of 2026-11-01. Not intent: the operator
decides whether and how any of it enters an intent file. Diagram:
<https://claude.ai/artifact/U4Z5NHp5MSvWGcNHeRcunA> (private to the operator
until shared).

Confidence marks: **[solid]** grounded in prior art or evidence;
**[plausible]** reasoned but untested here; **[speculative]** a framing, not a
finding.

## 1. Identity

**An autonomous platform team: three crafts working for an operator, that
maps, measures and improves any measurable system, starting with itself.**
[plausible]

| Role | Owns | Inside or outside |
|---|---|---|
| Systems engineer | structure: decomposition, interfaces, contracts, integration, sourcing parts | inside (the LLM) |
| Data scientist | evidence: measurement, models, experiments, validation | inside (the LLM) |
| DevOps / SRE | operation: sandbox, deploy, rollback, observability, budgets, drift | inside (the LLM) |
| Operator | purpose: goals, values, what counts as better, limits | **outside, always** |

If the system set its own standard of "better" it could always meet it. The
operator, and a judge the system cannot edit, stay outside. [solid]

The roles extend MLOps (data science plus DevOps) with systems engineering,
from *models in a system* to *any component in any system*. Closest field
names: ML systems engineering, platform engineering. [solid]

## 2. The loop

Nine steps in three groups. [solid as a pattern]

- **Know:** map (parts and connections), measure (quality and cost per part),
  catalog (what else exists that could fill each role).
- **Change:** locate (the bottleneck, or the gap against intent), source
  (reuse, configure, compose, generate, compile from traces), trial (sandbox
  or simulator).
- **Keep:** judge (better, by a standard the optimiser cannot touch), swap,
  record (losers too). Repeat: a swap changes the map.

Relatives: MAPE-K (no catalog, no outside judge); Theory of Constraints'
five focusing steps (locate made central); PDCA, the scientific method,
kaizen; evolution (variation, selection, retention); performance engineering
(profile, optimise the hot path, benchmark).

**What is distinctive [plausible]:** most loops skip **catalog** (they
generate instead of looking) and **map** (they treat the system as a blob
with one score, so they cannot locate the bottleneck, check that a swap keeps
interfaces, or move a part between systems). Map plus catalog is what lets the
loop *understand* a system and work on *other* systems.

## 3. Roles are skills; agents are chosen for properties

A role is a bundle of skills, tools and permissions; any agent can load it.
Spawn a subagent only for a property one shared context cannot give: [solid]

| Property | Use here |
|---|---|
| Context isolation | reading logs, traces, a target's code, catalog searches; only a summary returns |
| Parallelism | several candidates at once, each in its own worktree |
| Independence | blind review of a swap; independent forecasts whose errors do not correlate |
| Least privilege | explorers read only; the deployer applies only judged changes |
| Cheaper model | routine analysis and drafts on Haiku or Sonnet |
| Containment | risky trials and long searches, bounded and disposable |
| Fresh start | retry a failed attempt without its baggage |
| Background work | batch evaluations, long episodes |

- **The integrator** (the main Claude Code session) proposes and decides, and
  is the one place the whole picture lives.
- **The judge is not an agent.** It is a script outside the system's reach;
  code you cannot edit is more independent than any agent.
- **Avoid the org-chart pattern** (role-play agents chatting): lossy handoffs
  and multiplied tokens. Anthropic's multi-agent research write-up reported
  about 15× the tokens of a chat, paying off for wide parallel work; Cognition's
  "Don't Build Multi-Agents" argues the context-loss case.

Separation of duties without an org chart: the integrator proposes, isolated
workers build candidates in parallel, a blind reviewer checks where
independence matters, the locked judge scores, a narrowly permitted step
applies.

## 4. Platform practices that carry over

[solid]

| Practice | Here |
|---|---|
| SLOs | the constraints in "lowest cost within constraints"; the judge's bar |
| Error budgets | how much risk trials may spend; when spent, stop experimenting and stabilise |
| Golden paths | the playbook: recommended ways, left freely given evidence |
| Internal platform | catalogs, library, adapters: parts other systems reuse |
| Onboarding a service | onboarding a target: its adapter, and a judge agreed with the operator |
| Blameless postmortems | journal and archive, failures included |
| FinOps | cost ledger and cost ladder |

**Scope [plausible]:** "any system" means any system defined in software and
measurable: it has an adapter to read, run and swap parts, and a judge someone
agreed on. Software, ML pipelines, agents, simulated robots, real robots behind
a simulator. Not systems where nobody can say what better means.

## 5. Targets and adapters

[plausible]

- **Target adapter:** for one system, how to read its structure, run it,
  measure it and swap a component. Morphogen-on-itself is one adapter.
- **Map:** generated per target from code, config and traces (section 8).
- **Judge:** per target, operator-owned. The hardest part of each new target.
- **Library and catalogs:** shared across targets. A part proven in one target
  becomes a candidate for others; that is the transfer.

Self-improvement is the loop pointed at its own adapter; improving others is
the loop pointed at theirs.

Plan: **first target, the agent itself playing games** (free feedback);
**second target, something else with a clear judge** (a small ROS2 simulation
stack, or a codebase with a benchmark), which tests map, adapters and
attribution.

Outside the self, two things get harder: every target needs its own judge, and
swapping parts of someone else's system has side effects (deploying,
actuating, touching data), so it needs a sandbox or simulator and operator
approval.

## 6. First engagement: the agent JIT

The loop applied to one target (the agent's own behaviour) and one component
type (a model call). [plausible]

**It is a JIT compiler for an agent's behaviour.** The top LLM is the
interpreter; the log is the profiler; Claude Code is the compiler; program
scope is the guard; deferring to the LLM is deoptimisation. One difference: a
JIT must preserve meaning exactly, this may change behaviour when the judge
says outcomes are as good or better.

**Core rule:** a cheaper program that does as well or better replaces the more
expensive one. Everything is a program, including a prompt sent to a cheaper
model, so cheaper LLMs replacing dearer ones need no separate mechanism.

**Cost ladder** (every rung a program): code, rules, tables (≈ $0); local
8–12B model (GPU-seconds at a nominal rate); cheap API model; Haiku; Sonnet;
Opus as fallback and teacher.

**Inputs:** N sources of any shape (games, sensors, logs, feeds, files) through
thin adapters into one event envelope `{id, time, source, type, shape/dtype,
payload or reference, provenance}`. Situations are windows over the stream.

**Observation is compiled too:** parsers, detectors, change filters,
summarisers and attention programs. Most input should never reach an LLM.

**Outputs:** act through effectors, predict next events, update state, or
nothing.

**Signals for the judge:** prediction error on later events (universal,
unfakeable, needs no labels); rewards where a source has them; operator goals
and ratings. Games are sources with an extra reward channel, ideal for testing,
not part of the design.

**Program contract** (the interface every program follows): scope (and a
correct "not mine"), interface, `uses` (programs it calls), cost, record,
optional declared state (within an episode; across episodes only if declared).

**Structure, generated:** an index built from program headers is the
structural map; the call graph in the log shows real composition. The fixed
frame (judge, adapters, LLM fallback, log, library) is a short list in
`CLAUDE.md`.

**Decomposing behaviour:** when the LLM answers it tags a short subgoal, so hot
spots group by subgoal and programs become options (Sutton, Precup and Singh):
start condition, policy, end condition.

**Lookup order:** own library, archive (near-misses), catalogs, then write new.

**Memory:** Claude Code's on-disk defaults for the integrator's notes; the log
(episodic), library (procedural and compiled), playbook (advice), journal
(rationale), archive (failures). No world-knowledge store in the core; memory
is a program with state that the judge admits if outcomes improve.

**Hooks toward a fuller cognitive model** (section 11): the LLM can call
library programs as tools (imagination and planning once a simulator exists);
surprise as a first-class signal (curiosity, urgency); a fast episodic write
path mid-run; queryable log for recall.

**Hard parts:** scope and deferral (overclaiming programs fail silently);
imitation first, outcomes later; library bloat (retire unused programs).

**Measures:** outcomes (prediction error, rewards, held-out results); cost per
hour of input or per episode; share of input dropped or handled without an
LLM; fall-through rate (rises with novelty).

**First experiment:** the LLM plays Crafter every N steps or by macro-actions;
after each batch, `compile` runs; plot score, cost and fall-through rate over
iterations.

## 7. First principles

Facts that cannot be reduced further: [plausible]

1. The world is only partly known.
2. Every model is a compression of experience, and no compression is best for
   all data (no free lunch).
3. Resources are finite; thinking is worth it only when expected gain beats
   its cost.
4. Outcomes are the only source of truth; they are noisy and delayed, and
   whatever optimises against a measure will exploit it (Goodhart).
5. The world changes and brings new things.
6. The reasoner is fixed: the LLM's weights do not change, so all adaptation
   lives outside it.
7. Values are given, not learned.

What follows: choosing a representation is a priced decision (minimum
description length, resource-rationality; "lowest cost within constraints" is
this); the judge is separate and grounded in outcomes; hold data out and keep
exploring; adaptation lives in artifacts and records; intent is input, never
optimised.

**One-way doors, get right now [solid]:** the judge and its feedback; the
record format (versions, context, decision, outcome, cost, so the system can be
re-cut later); safety boundaries. **Two-way doors, start light:** map schema,
card format, decision-point list, memory store, whether a part is a skill,
script, prompt or model.

**Is the cut right? [plausible]** Measure from the archive: locality (most
improvements touch one artifact), attribution (score changes trace to
artifacts), reuse (artifacts work across contexts and targets). If low after a
few dozen trials, re-cut.

## 8. The map is a decision space

[solid] Every slot is a decision: alternatives are options, KPIs criteria,
lock the decider, journal the rationale. Relatives: Zwicky's general
morphological analysis, AutoML conditional configuration spaces
(ConfigSpace), influence diagrams, architecture decision records, feature
models.

[plausible] Two kinds of decision: design time (what is installed; a choice)
and run time (which option now; a policy). **A slot holds either a fixed choice
or a policy over options.** A full decision map adds per slot: options with
track records, criteria, uncertainty (which says what to revisit), constraints,
status, decider, rationale. With decision records per trial, track records and
uncertainty are computed, not maintained.

The pattern is recursive (as in Backstage and C4): a system is made of
components and any component can be a system. Claude Code is one such system
inside Morphogen, with model, instructions, context window, file memory,
skills, subagents, hooks, permissions, MCP servers, plugins and headless mode
as its parts; mapped, it shows where the system can change itself.

## 9. The playbook: the crafts as methodology

[plausible] "Aiding the LLM" means giving it the three crafts, not a taxonomy.
The playbook is advice with a track record, revised on evidence.

**Data science:** frame the problem; baseline first; look at the data before
modelling; try several model families (graph, vector, simulator, causal model,
solver, rules, statistics, LLM reasoning, distilled policy); guard against
leakage (gaming the judge is leakage); beware choosing the winner by luck after
many trials (refresh held-out data, count trials); track every experiment; ship
the simplest model that clears the bar; watch for drift. References: CRISP-DM,
Google's "Rules of Machine Learning", the Kaggle playbook.

**Systems engineering:** decompose by interfaces; contracts before contents;
impact analysis before swaps; reuse before build.

**DevOps / SRE:** sandbox first; small reversible changes; rollback ready;
observe everything; respect the error budget.

**Program shapes and when they tend to win:** lookup or cache (exact repeats);
rules (few conditions, crisp boundaries); graph (relations and paths); vector
index (fuzzy similarity); small classifier or regressor (many noisy features);
search or planner (combinatorial choices with known rules); simulator
(dynamics you can step); cheaper LLM with a tuned prompt (language-shaped
tasks); cascade or combination.

**Combination patterns:** hybrid retrieval (graph plus vector), cascade,
distillation, residual (physics or rules plus a learned correction), prior and
posterior, surrogate, hierarchy (planner over controller), verification,
gating, ensemble plus reconciliation.

**Decision-point checklist:** attending, observing, interpreting,
remembering, predicting, explaining, counterfactuals, valuing, deciding,
planning, acting, modelling others, communicating, verifying, learning,
metacognition, self-modelling. Accept a point only if it recurs, its outcome
can be scored, and more than one shape is plausible.

**Procedures that keep the LLM from following habit:** propose at least two
different shapes per hot spot; check the catalog first; record which shape won
where.

Guidance comes in three kinds: **constraints** (judge, intent; fixed),
**interface** (the program and component contracts; changed only through the
gate), **knowledge** (this playbook; revisable on evidence).

## 10. Where the operator's earlier instincts went

- **Morphogenetics → how structure grows.** The top LLM is the stem cell;
  programs are cells that specialise where the judge's signals favour them.
- **Gamability → the judge.** Outside the system's reach: hidden held-out data,
  predictions scored by events that have not happened yet.
- **Aiding the LLM → the playbook.** Dimensions and options became advice with
  a track record, not architecture.
- **Modelling everything as a graph → one option among many.** Graphs remain a
  good interchange and registry; working models are whatever wins.

## 11. How far from a cognitive model

[plausible] Against the Common Model of Cognition (Laird, Lebiere and
Rosenbloom, 2017): strong on perception, action, procedural memory and
learning (compilation, like Soar's chunking and ACT-R's production
compilation), offline consolidation and forgetting; partial on confidence,
goals, prediction, episodic memory, working memory; missing fast learning from
one experience, intrinsic motivation, recall while running, deliberate
imagination and planning, affect or priority. The four hooks in section 6
close most of the gap, each as programs the judge admits only if outcomes
improve. A cognitive model is not the goal; the goal is the platform team.

## 12. Stack (all optional seed parts)

Operator decisions: runs on the operator's machine with Docker; the operator
wants to **watch it play** and work; model tiers used side by side (local
8–12B, OpenRouter, Haiku, Sonnet, Opus); goal **lowest cost within
constraints**. Ollama, Bifrost and the rest are optional seeds, not core;
model choice and savings are a big deal.

- **Lexicographic gate:** first held-out outcomes do not regress (or stay above
  an operator target) and latency fits; then lower cost wins.
- **Cost ledger** in the record schema: per call model, tokens, price,
  dollars; local models at GPU-seconds × a nominal rate; integrator
  subscription usage in its own column.
- **Subscription and API:** the Claude subscription covers Claude Code's own
  traffic. Through Bifrost: sign in with `/login`, set `ANTHROPIC_BASE_URL` to
  Bifrost's `/anthropic` route and send the virtual key in
  `ANTHROPIC_CUSTOM_HEADERS` (`x-bf-vk`); do not set `ANTHROPIC_AUTH_TOKEN`,
  `ANTHROPIC_API_KEY` or `apiKeyHelper`. Bifrost then logs and governs the
  integrator's traffic while billing stays on the subscription; usage limits
  still apply. Game code cannot reuse that token; its calls use API keys,
  OpenRouter or local models.

| Slot | Seed | Alternative |
|---|---|---|
| Model gateway | Bifrost (Go, Apache 2.0; Ollama, OpenRouter, Anthropic; per-key budgets; USD cost tracking) | LiteLLM |
| Local models | Ollama | llama.cpp server, vLLM |
| Viewer | Rerun (live and recorded, per step: frame, action, program, model, cost) | Gymnasium `RecordVideo` |
| Call tracing | Arize Phoenix | — |
| Sources | Gymnasium API; Crafter first; MiniHack, ARC-AGI-3 held out | Craftax with a GPU |

Check during setup: OpenRouter cost passes through Bifrost; Bifrost exports
OpenTelemetry to Phoenix; capability matrix for the models used. Candidates are
listed in `catalogs.yaml` under `parts`.

Layout for a fresh repository:

```
CLAUDE.md        the role, the loop, the fixed frame (short)
intent.md        goals, SLOs, error budget, money budget, autonomy (operator)
judge/           scoring and validity checks, read-only mount (operator)
targets/         one adapter per target (self, games, ...)
library/         programs and parts: code or prompt + contract + record
catalogs.yaml    where to look before building
playbook/        the crafts as skills, revisable
log/             events, calls, costs, outcomes (raw ignored, summaries kept)
journal/
```

Hidden held-out evaluation lives outside the agent's repository (CI or a
private repository). Two lock levels: operator-owned, and open through the
gate. Isolation from the devcontainer and CI, not from pattern matching. Every
structured file the agent writes gets a validity check in the judge (a
malformed `catalogs.yaml` passed this repository's gate on 2026-11-01).

## 13. Prior art

From first searches; summaries, not full readings.

- **Closest relatives of the multi-paradigm idea:** OpenCog Hyperon, cognitive
  synergy over a shared metagraph ([paper](https://arxiv.org/pdf/2310.18318));
  Epstein's portfolio architecture
  ([pdf](https://www.cs.hunter.cuny.edu/~epstein/papers/aaai%20fall%20sympoium%202009.final3.pdf));
  rep2rep ([Cambridge](https://www.repository.cam.ac.uk/handle/1810/297673),
  [Springer](https://link.springer.com/chapter/10.1007/978-3-030-86062-2_43));
  Polyscheme; Peebles and Cheng
  ([Huddersfield](https://pure.hud.ac.uk/en/publications/multiple-representations-in-cognitive-architectures-2/)).
- **LLMs choosing or inventing methods:** Self-Discover
  ([HF](https://huggingface.co/papers/2402.03620)); Auto-Evolve
  ([arXiv](https://arxiv.org/html/2410.06328v2)); Adaptive LLM-Symbolic
  Reasoning ([arXiv](https://ar5iv.arxiv.org/html/2510.06774)); When Do
  Symbolic Solvers Enhance Reasoning
  ([NeurIPS 2025](https://neurips.cc/virtual/2025/126669)); CodeSteer
  ([blog](https://chrisg777.github.io/blog/2025/ml-tea-llms-symbolic-computing/)).
- **World models on demand:** Li, Fox and Goodman
  ([arXiv](https://arxiv.org/abs/2402.17879v1)); Wong et al.
  ([arXiv](https://www.arxiv.org/pdf/2507.12547)); probabilistic framework for
  LLM model discovery ([arXiv](https://arxiv.org/html/2602.18266v1)); mixture
  of world models, ICLR 2026
  ([pdf](https://proceedings.iclr.cc/paper_files/paper/2026/file/33b47b3d2441a17b95344cd635f3dd01-Paper-Conference.pdf)).
- **Forecast aggregation:** AIA Forecaster
  ([arXiv](https://arxiv.org/html/2511.07678v1)); LEAP
  ([arXiv](https://arxiv.org/pdf/2609.01337)).
- **Compiling deliberation into skill:** Soar's chunking; ACT-R's production
  compilation; FrugalGPT and LLM cascades; DreamCoder; Voyager; Code as
  Policies; the options framework (Sutton, Precup and Singh, 1999); JIT
  compilers (V8, PyPy, HotSpot).
- **LLM data scientists:** AIDE, DS-Agent, MetaGPT's Data Interpreter, MLE-bench,
  Sakana's AI Scientist. They work on a given dataset and task, once.
- **Loops and operations:** MAPE-K and Rainbow (self-adaptive systems), Theory
  of Constraints, PDCA, SRE (SLOs, error budgets), platform engineering,
  CRISP-DM.
- **Decision spaces:** Zwicky's morphological analysis, ConfigSpace and SMAC,
  influence diagrams, architecture decision records, feature models.
- **Self-improving agents:** Darwin Gödel Machine, ADAS, AlphaEvolve and
  OpenEvolve, GEPA, auto-sklearn, AutoGluon.
- **Cognition:** Common Model of Cognition; Minsky; rational metareasoning
  (Russell and Wefald; Lieder and Griffiths); Rice's algorithm selection
  problem.
- **Multi-agent costs:** Anthropic's multi-agent research system write-up;
  Cognition, "Don't Build Multi-Agents".

**What looks open (unverified):** a general coding agent that compiles itself
away under outcomes it cannot touch, in open-ended domains; a data scientist
embedded in a running system, working continuously and deploying its own
results under an outside judge; one loop with map and catalog that transfers
parts between systems, itself included; evidence that combining paradigms
beats selecting.

## 14. Next steps and open decisions

Proposed order, one-way doors first:

1. Record schema with the cost ledger, subgoal tags and call graph.
2. Judge with validity checks, SLOs and a hidden held-out set outside the
   repository.
3. First target adapter: the agent playing Crafter; viewer.
4. `compile` skill and the program contract; first JIT experiment.
5. Second target with a clear judge; measure locality, attribution, reuse.

Operator decisions:

- New repository (create it empty) and its name.
- Operator machine: OS, GPU and VRAM (8B at 4-bit needs about 6 GB, 12B about
  8–9 GB).
- Monthly API cap; SLOs and error budget; the score constraint for cheaper
  tiers.
- In this repository: the guard blocks pushing archive tags the gate wrote, so
  they stay local.
