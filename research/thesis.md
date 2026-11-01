# Thesis: a regime selector and constructor, trained on games

Working note from the operator session of 2026-11-01. Not intent: the operator
decides whether and how any of it enters `map/intent.md`.

Confidence marks: **[solid]** grounded in prior art or evidence;
**[plausible]** reasoned but untested here; **[speculative]** a framing, not a
finding.

## 1. First principles, and where to cut

What any adaptive system needs, and what Morphogen has: **[solid]**

| Principle | Meaning | Status |
|---|---|---|
| Variation | generate candidates | strong: LLM, catalogs, strategies, subagents |
| Feedback | a signal of what worked | **weak**: structural checks only |
| Retention | keep what works, remember what failed | strong: git, gate, archive, journal |
| Credit assignment | which part caused the outcome | **missing** |
| Abstraction | compress experience into reusable units | partial: skills, strategies; no distillation |
| Allocation | where effort goes | partial: improvement strategies |
| Timescales | fast (in-step), medium (across episodes), slow (architecture) | mixed, not separated |

**The shaping constraint [solid]:** the top-level LLM does not learn; its
weights are fixed. All adaptation must live outside it, in files, code, small
models and records.

**The unit [plausible]:** a *versioned, executable, scorable artifact with a
record of where it was used*. A skill, a strategy card, a component and a
distilled model are each one. Structure (where it plugs in), procedure (how it
is built or chosen), representation (which paradigm) and function (which
decision it serves) are labels on that unit, not competing framings.

**One-way doors, get right now [solid]:**

1. The judge and its feedback: hard to game, out of the agent's reach, fed by
   real outcomes.
2. The record format: every trial logs artifact versions, context, decision,
   outcome and cost. Good records allow re-cutting later; bad ones lose early
   data for good.
3. Safety boundaries: locks, autonomy, budgets (already in place).

**Two-way doors, start light [solid]:** graph schema, strategy-card format,
the list of decision points, the memory store, whether a part is a skill, a
script or a model.

**Is the cut right? Measure it from the archive [plausible]:**

- *Locality:* most improvements touch one artifact.
- *Attribution:* score changes trace to specific artifacts.
- *Reuse:* artifacts work in more than one context or game without edits.

If these stay low after a few dozen trials, re-cut.

## 2. The thesis

**[plausible]** The value is not a harness that rewrites itself. It is
**decision points** that **choose, combine or construct** models from
different paradigms (graph, vector, simulator, causal model, solver, rules,
statistical model, LLM reasoning, distilled policy) for the situation at hand,
learn which works from scored outcomes, and over time **compile** slow LLM
reasoning into fast, cheap parts. Self-modification remains as the slow outer
loop that improves portfolios and selectors; the locked judge, archive and
autonomy dial keep it honest.

**[speculative]** One step up the ladder:

| Level | Answers |
|---|---|
| Tools | what can I do |
| Skills | how do I do it |
| Models | what is true and what will happen |
| Meta-models | which way of seeing fits; choose, combine or build one |

The hard parts are not choosing from a menu but **inventing** representations
and **combining** them coherently. Both are open problems.

## 3. The map is a decision space

**[solid]** Every slot is a decision: alternatives are options, KPIs are
criteria, the lock says who decides, the journal holds the rationale. The
blueprint is already half a decision model. Related forms: Zwicky's general
morphological analysis (dimensions × options plus cross-consistency), AutoML
conditional configuration spaces (ConfigSpace), influence diagrams (decision,
chance and utility nodes), architecture decision records, software
product-line feature models.

**[plausible]** Two kinds of decision:

| | Design time | Run time |
|---|---|---|
| Question | what is installed in this slot | which option now, for this situation |
| Decided by | trial, gate, operator | the selector, each time |
| Output | a choice | a policy: situation → option(s) |

**A slot holds either a fixed choice or a policy over options.** A slot filled
by a selector is a run-time decision point. This joins the component map, the
strategy library and the regime selector into one model.

To become a full decision map, each slot needs: options with track records;
criteria (KPIs, cost, latency); uncertainty about each option (the missing
chance nodes, which also say which decision to revisit); constraints between
options; status (open, decided, policy, review); decider (lock, autonomy);
rationale (journal and archive links). If every trial writes a decision record,
track records and uncertainty can be **computed** from records, not kept by hand.

**[plausible]** The pattern is recursive: a system is made of components, and
any component can be a system (as in Backstage and C4). One node shape at every
level: provides/consumes, interface, KPIs, lock, alternatives, status.

## 4. The harness: Claude Code

**As the top-level loop [plausible]:**

- An interactive or headless session is the **integrator**: it watches the
  whole system, designs and combines components, reads the archive and
  journal, decides what to try next.
- **Smaller models do routine work** (small LLMs, classifiers, distilled
  policies, solvers), reachable through tools or MCP; this environment can
  reach OpenRouter. The top level designs and compiles; it does not sit in the
  fast loop.
- Why Claude Code: many points of modification (skills, hooks, subagents,
  settings, MCP, headless mode), regarded as the strongest coding harness,
  usable on a Claude subscription. Check plan limits and terms for unattended
  runs.

**As a mapped system [plausible].** Today it is one opaque node
(`operator-session`). Mapped, it shows where the system can change itself:

| Component | Where | Role | Lock |
|---|---|---|---|
| Model | settings, session | top-level reasoner | locked |
| Instructions | built-in prompt, `CLAUDE.md` | standing behaviour | locked |
| Context window | runtime | working memory; compaction is its policy | observed only |
| File memory | `CLAUDE.md` files, auto-memory | default long-term memory | gated |
| Skills | `.claude/skills/` | procedures | gated |
| Subagents | `.claude/agents/` (none) | delegated workers; slot for cheap models | gated |
| Hooks | `.claude/settings.json` → `tools/hooks/` | enforcement, observation, traces | locked |
| Permissions | `.claude/settings.json` | reach | locked |
| MCP servers | `.mcp.json` (none) | adapters to tools, small LLMs, simulators | gated |
| Plugins | marketplace | bundles of the above | gated |
| Headless | `claude -p`, `tools/headless` | unattended outer loop | gated, autonomy 4 |

Parts of the harness are closed and change per release: record what is
observable, mark the rest `observed only`.

## 5. Seed portfolio, and memory

**[solid]** Morphogen already ships memory, as plain files in git:

| Kind | Holds | Shipped as |
|---|---|---|
| Self-model | what I am made of | `map/blueprint.yaml`, as-built map |
| Index | where options are | `catalogs.yaml` |
| Procedural | how to do things | `.claude/skills/`, `strategies/` |
| Episodic, narrative | what I did and why | `journal/` |
| Episodic, scored | what I tried and how it scored | `archive/*` tags |
| Values and goals | what matters, what is forbidden | `map/intent.md`, `CLAUDE.md` |
| Judgement | what counts as better | `evals/` |
| Working | what is in view | context window (unmanaged) |

**Principle:** ship a **seed portfolio**, the simplest working default in each
slot, every one replaceable by trial.

**Core-primitive test [plausible]:** a part is core only if the loop cannot
run, or cannot stay safe, without it. Judge, goals, archive and journal,
procedures: core. Self-model and index: core as replaceable seeds.
**World-knowledge store: not core, an empty slot.** Its shape depends on the
domain; world knowledge already lives in the LLM's weights and in the
portfolio's models (a learned dynamics model *is* compressed world knowledge);
and it is a good first test of the thesis: start without it and see whether
the system discovers it needs one. Baseline any chosen store must beat: plain
files plus grep.

## 6. Modelling strategies as a library

**[plausible]** Slots say *where* things plug in; a strategy library says *how*
to model a kind of situation. They connect: the selector chooses a strategy,
the strategy builds or configures a model, the model fills a slot, the judge
scores it, the graph records which strategy produced what. Morphogen already
does this one level up for improvement strategies.

Skill format as the container: native to Claude Code, descriptions act as a
cheap index, can bundle scripts and references, versioned. Fixes for its
limits:

1. Prose cannot run or be scored: the executable part goes in `scripts/`, the
   scoring in the judge.
2. Selection by reading has no memory: each card carries a track record from
   the archive.
3. Context bloat: keep modelling strategies in `strategies/modeling/` as
   unregistered skill-format files, with one registered `model-select` skill
   that searches them (with an index once the library grows).
4. A few cards will dominate (Auto-Evolve's finding): usage and score stats
   guide pruning and invention.

```yaml
name: graph-plus-vector-recall
applies_when: many named entities; lookups by relation and by similarity
paradigms: [graph, vector]
interface: remember(event) / recall(query) -> items
cost: low; latency ms
implementation: scripts/recall.py
scored_by: eval:recall_at_k on game episodes
record: {trials: 0, wins: 0, archive: []}
```

## 7. Ways to combine paradigms

**[solid]** The integrator's menu:

| Pattern | Example |
|---|---|
| Hybrid retrieval | graph plus vector, either narrowing the other |
| Cascade | cheap model answers when confident, passes hard cases up |
| Distillation | LLM decisions or an online-learned index become a small model or rules |
| Residual | physics or rules model plus a learned correction |
| Prior and posterior | one model's output seeds another's update |
| Surrogate | fast stand-in for a slow simulator, re-checked |
| Hierarchy | slow planner sets goals for a fast controller |
| Verification | one paradigm proposes, another checks |
| Gating | learned gate weights experts per situation |
| Ensemble plus reconciliation | independent models, a supervisor resolves disagreement |

## 8. Decision points

**[solid]** A checklist, not a fixed taxonomy: attending, observing,
interpreting, remembering, predicting, explaining, counterfactuals, valuing,
deciding, planning, acting, modelling others, communicating, verifying,
learning, metacognition, self-modelling.

Accept a point only if it recurs, its outcome can be scored, and more than one
paradigm is plausible. Predicting, diagnosing, remembering and verifying are
the easiest first experiments; valuing and modelling others the hardest.

## 9. Games as training and test ground

**[solid]** Free, unlimited, hard-to-game feedback that needs several kinds of
model at once. Existing environments used as test beds:

- Inner loop: Crafter or Craftax (cheap, open-ended).
- Hidden held-out set: different games (MiniHack levels, ARC-AGI-3 if
  available), so gains must generalise.
- Later: robotics simulators (MuJoCo, ManiSkill, PyBullet), same harness.
- Prefer turn-based or pausable environments while compiled parts are immature.

## 10. Measures and falsifiable steps

**KPIs [plausible]:** score on development games; score on held-out games;
score per dollar; share of decisions made without the top-level LLM at equal
score (the compiling measure); locality, attribution and reuse (is the cut
right).

**Steps:**

1. **Selector gain:** a learned selector over 3 to 5 paradigms beats the best
   single one on held-out games. (Alone, this is a good router.)
2. **Combination gain:** combined answers beat selected ones.
3. **Construction:** the system adds a new paradigm or combination that joins
   the portfolio and wins somewhere.

**Disconfirmed if:** one strong LLM with tools matches it everywhere;
selection costs more than it gains; gains vanish on held-out games.

## 11. Fresh start: operator decisions and stack

Decided by the operator (2026-11-01):

- **Runs on the operator's machine with Docker.** The operator wants to
  **watch it play** and work.
- **Model tiers**, used side by side: local 8–12B models, OpenRouter, Haiku,
  Sonnet, Opus.
- **Goal: lowest cost within constraints.**

Consequences **[plausible]**:

- **Cost ladder as a slot:** the policy is the cheapest tier that meets the
  constraint. Tiers: 0 compiled rules or distilled policy; 1 local 8–12B;
  2 cheap OpenRouter models; 3 Haiku; 4 Sonnet; 5 Opus, rarely, as teacher or
  for hard cases. Upper tiers' decisions become training data for tiers 0–1.
- **Lexicographic gate:** first, held-out score does not regress (or stays
  above an operator target) and latency fits; then, lower cost per episode is
  better.
- **Cost ledger in the record schema:** per call model, tokens, price,
  dollars; local models at GPU-seconds × a nominal rate, so they are not free;
  the integrator's subscription usage in a separate column.
- **Subscription versus API:** the Claude subscription covers the Claude Code
  integrator. Claude models called from game code go through the API and are
  billed per token; do not route per-step calls through `claude -p`.
- **The game loop pays for itself only if compiled:** Crafter episodes run for
  thousands of steps, so the top LLM acts through macro-actions or every N
  steps, and the rest must be compiled. That pressure is the thesis.

Stack (candidates in `catalogs.yaml` under `parts`; pin versions and digests):

| Slot | Choice | Alternative |
|---|---|---|
| Model gateway | **Bifrost** (Go, Apache 2.0; Ollama, OpenRouter, Anthropic; per-key budgets; USD cost tracking) | LiteLLM |
| Local models | Ollama | llama.cpp server, vLLM |
| Game viewer | Rerun (live and recorded, per-step frame, action, card, model, cost) | Gymnasium `RecordVideo` mp4s |
| Call tracing | Arize Phoenix | — |
| Environments | Gymnasium API; Crafter first; MiniHack, ARC-AGI-3 held out | Craftax with a GPU |

Check during setup: OpenRouter cost passes through Bifrost; Bifrost exports
OpenTelemetry to Phoenix (otherwise the client sends spans); capability matrix
for the models used. Bifrost cannot price local tokens; the ledger does.

Layout for the fresh repository:

```
CLAUDE.md        loop and rules, short
intent.md        purpose, KPIs, budgets, autonomy (operator)
space.yaml       decision space: nested systems, slots (choice | policy)
cards/           modelling strategies, skill format, scripts, contracts
.claude/skills/  map, model-select, trial, distill
envs/            environment adapters
judge/           dev evaluation, read-only mount (operator)
records/         decision records with cost ledger (committed)
runs/            raw traces and episodes (ignored)
catalogs.yaml, journal/
```

Hidden held-out evaluation lives outside the agent's repo (CI or a private
repo); the agent can read anything in its own repo. Two lock levels:
operator-owned, and open through the gate. Isolation from the devcontainer and
CI, not from pattern matching.

Phases, each ending in a measurement: 0 frame (records, judge, Crafter,
baselines, viewer, held-out set); 1 selector gain; 2 compiling (share without
the LLM rises at equal score); 3 combination and construction; 4 transfer to a
second game, then a robotics simulator.

## 12. Prior art

From a first search; summaries, not full readings. **[solid]** as pointers.

- **OpenCog Hyperon**, cognitive synergy over a shared metagraph: closest
  relative; combining paradigms is where it has stalled.
  [paper](https://arxiv.org/pdf/2310.18318)
- **Representation selection:** Epstein's portfolio architecture
  ([pdf](https://www.cs.hunter.cuny.edu/~epstein/papers/aaai%20fall%20sympoium%202009.final3.pdf)),
  rep2rep ([Cambridge](https://www.repository.cam.ac.uk/handle/1810/297673),
  [Springer](https://link.springer.com/chapter/10.1007/978-3-030-86062-2_43)),
  Polyscheme, Peebles and Cheng
  ([Huddersfield](https://pure.hud.ac.uk/en/publications/multiple-representations-in-cognitive-architectures-2/)).
- **LLMs choosing reasoning methods:** Self-Discover
  ([HF](https://huggingface.co/papers/2402.03620)); Auto-Evolve
  ([arXiv](https://arxiv.org/html/2410.06328v2)).
- **Routing between paradigms:** Adaptive LLM-Symbolic Reasoning
  ([arXiv](https://ar5iv.arxiv.org/html/2510.06774)); When Do Symbolic Solvers
  Enhance Reasoning ([NeurIPS 2025](https://neurips.cc/virtual/2025/126669));
  CodeSteer ([blog](https://chrisg777.github.io/blog/2025/ml-tea-llms-symbolic-computing/)).
- **World models on demand:** Li, Fox and Goodman
  ([arXiv](https://arxiv.org/abs/2402.17879v1)); Wong et al.
  ([arXiv](https://www.arxiv.org/pdf/2507.12547)); probabilistic framework for
  LLM model discovery ([arXiv](https://arxiv.org/html/2602.18266v1)).
- **Mixture of world models** (ICLR 2026)
  ([pdf](https://proceedings.iclr.cc/paper_files/paper/2026/file/33b47b3d2441a17b95344cd635f3dd01-Paper-Conference.pdf)).
- **Forecast aggregation:** AIA Forecaster
  ([arXiv](https://arxiv.org/html/2511.07678v1)), LEAP
  ([arXiv](https://arxiv.org/pdf/2609.01337)).
- **Decision spaces:** Zwicky's general morphological analysis; ConfigSpace
  and SMAC; influence diagrams; architecture decision records; feature models.
- **Libraries of procedures:** Voyager, Agent Workflow Memory, Agent Skills,
  DreamCoder.
- Background: Minsky, Rice's algorithm selection problem, rational
  metareasoning (Russell and Wefald; Lieder and Griffiths), Darwin Gödel
  Machine, AlphaEvolve, GEPA, auto-sklearn, AutoGluon, Rainbow and MAPE-K.

**What looks open:** learned selection across genuinely different paradigms at
run time; a portfolio that grows by trial under a judge the agent cannot edit;
one selection interface across many decision points; evidence that combining
beats selecting.

## 13. Next steps and open decisions

Proposed order, one-way doors first:

1. **Trace and record schema** that every trial writes (hooks can capture much
   of it).
2. **One game environment wired to the judge.**
3. **Three or four strategy cards** on one decision point, plus `model-select`.
4. **Blueprint changes:** decision fields per slot; Claude Code as a mapped
   system; slots that hold a choice or a policy.

Operator decisions:

- Whether this becomes Morphogen's purpose (via `onboard`), or a new repository.
- Repository name (operator creates it empty).
- Operator machine: OS, GPU and VRAM (8B at 4-bit needs about 6 GB, 12B about 8–9 GB).
- Monthly API cap, and the score constraint (for example, match a
  Sonnet-every-N-steps baseline).
- Guard: it blocks pushing archive tags the gate wrote, so they stay local.
