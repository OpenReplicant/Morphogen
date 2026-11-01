# Thesis: a regime selector and constructor, trained on games

Working note from the operator session of 2026-11-01. Not yet intent: the
operator decides whether and how it enters `map/intent.md`.

## The idea

The value is not a harness that rewrites itself. It is **decision points** in
the harness that **choose, combine or construct** models from different
paradigms (graph, vector, simulator, causal model, solver, rules, statistical
model, LLM reasoning, distilled policy) for the situation at hand, learn which
works from scored outcomes, and over time **compile** slow LLM reasoning into
fast, cheap parts.

Self-modification stays, as the slow outer loop that improves the portfolios
and selectors. Morphogen's locked judge, archive and autonomy dial are what
keep that loop honest.

One step up the ladder:

| Level | Answers |
|---|---|
| Tools | what can I do |
| Skills | how do I do it |
| Models | what is true and what will happen |
| Meta-models | which way of seeing fits this situation; choose, combine or build one |

## Claude Code as the top-level loop

- An interactive or headless Claude Code session is the **integrator**: it
  watches the system as a whole, designs and combines components, reads the
  archive and journal, and decides what to try next.
- **Smaller models do the routine work**: small LLMs, classifiers, distilled
  policies, solvers. The top level designs and compiles; it does not sit in
  the fast loop.
- Why Claude Code: many points of modification (skills, hooks, subagents,
  settings, MCP, headless mode), widely regarded as the strongest coding
  harness, and usable on a Claude subscription. Check plan limits and terms
  for unattended runs.
- Small models are reachable through tools or MCP (this environment can reach
  OpenRouter, for example).

## Self-model: ship a graph, let it be replaced

- The blueprint graph is a **starting scaffold**: it gives the system a
  concept of *slots and connections* from day one, which it can correct and
  expand.
- It is itself a slot. The system may swap its self-representation later if a
  trial shows something better.
- To make the graph earn its place: generate it (mapper script, runtime
  traces) rather than writing it by hand; give interfaces typed contracts so a
  swap can be checked; attribute score to components so the search aims at the
  bottleneck; use it for impact analysis to pick which tests to run.

## Memory: a catalog and a workbench, not a prescription

- No built-in epistemic memory (Graphiti, Cognee or similar). There are many
  ways to model memory; a developed system can opt for one.
- Give the agent a **catalog** (where to find options) and a **workbench**
  (a sandboxed place to build, combine and benchmark candidates against the
  judge), and let trials decide.
- Generalises: every slot gets catalog plus workbench, not a default answer.

## Ways to combine paradigms (the integrator's menu)

| Pattern | Example |
|---|---|
| Hybrid retrieval | graph plus vector, either one narrowing the other |
| Cascade | cheap model answers when confident, passes hard cases up |
| Distillation | LLM decisions or an online-learned index become a small model or rules |
| Residual | physics or rules model plus a learned correction |
| Prior and posterior | one model's output seeds another's update |
| Surrogate | fast learned stand-in for a slow simulator, re-checked |
| Hierarchy | slow planner sets goals for a fast controller |
| Verification | one paradigm proposes, another checks |
| Gating | learned gate weights experts per situation |
| Ensemble plus reconciliation | independent models, a supervisor resolves disagreement |

## Decision points (a checklist, not a fixed taxonomy)

Attending, observing, interpreting, remembering, predicting, explaining,
counterfactuals, valuing, deciding, planning, acting, modelling others,
communicating, verifying, learning, metacognition, self-modelling.

Accept a point only if it recurs, its outcome can be scored, and more than one
paradigm is plausible. Predicting, diagnosing, remembering and verifying are
the easiest first experiments.

## Games as training and test ground

Free, unlimited, hard-to-game feedback that needs several kinds of model at
once (perception, maps, dynamics, planning, memory). Existing environments
used as test beds:

- **Inner loop:** Crafter or Craftax (cheap, open-ended).
- **Hidden held-out set:** different games (MiniHack levels, ARC-AGI-3 if
  available), so gains must generalise.
- **Later:** robotics simulators (MuJoCo, ManiSkill, PyBullet) with the same
  harness.
- Prefer turn-based or pausable environments while compiled parts are immature.

Candidate KPIs:

1. score on development games
2. score on held-out games
3. score per dollar
4. share of decisions made without the top-level LLM, at equal score (the
   compiling measure)

## Falsifiable steps

1. **Selector gain:** a learned selector over 3 to 5 paradigms beats the best
   single one on held-out games. (If only this holds, it is a good router.)
2. **Combination gain:** combined answers beat selected ones.
3. **Construction:** the system adds a new paradigm or combination that joins
   the portfolio and wins somewhere.

Disconfirmed if one strong LLM with tools matches it everywhere, if selection
costs more than it gains, or if gains vanish on held-out games.

## Prior art (from a first search; summaries, not full readings)

- **OpenCog Hyperon**, cognitive synergy over a shared metagraph: the closest
  relative; combining paradigms is where it has stalled.
  [paper](https://arxiv.org/pdf/2310.18318)
- **Representation selection:** Epstein's portfolio architecture
  ([pdf](https://www.cs.hunter.cuny.edu/~epstein/papers/aaai%20fall%20sympoium%202009.final3.pdf)),
  rep2rep ([Cambridge](https://www.repository.cam.ac.uk/handle/1810/297673),
  [Springer](https://link.springer.com/chapter/10.1007/978-3-030-86062-2_43)),
  Polyscheme, Peebles and Cheng
  ([Huddersfield](https://pure.hud.ac.uk/en/publications/multiple-representations-in-cognitive-architectures-2/)).
- **LLMs choosing reasoning methods:** Self-Discover
  ([HF](https://huggingface.co/papers/2402.03620)); Auto-Evolve, which found a
  fixed module set gets dominated and invents modules
  ([arXiv](https://arxiv.org/html/2410.06328v2)).
- **Routing between paradigms:** Adaptive LLM-Symbolic Reasoning
  ([arXiv](https://ar5iv.arxiv.org/html/2510.06774)); When Do Symbolic Solvers
  Enhance Reasoning, evidence that the winner depends on the regime
  ([NeurIPS 2025](https://neurips.cc/virtual/2025/126669)); CodeSteer
  ([blog](https://chrisg777.github.io/blog/2025/ml-tea-llms-symbolic-computing/)).
- **Building world models on demand:** Li, Fox and Goodman
  ([arXiv](https://arxiv.org/abs/2402.17879v1)); Wong et al., on-demand
  synthesis of probabilistic models ([arXiv](https://www.arxiv.org/pdf/2507.12547));
  a probabilistic framework for LLM model discovery
  ([arXiv](https://arxiv.org/html/2602.18266v1)).
- **Mixture of world models** (ICLR 2026), learned routing within one paradigm
  ([pdf](https://proceedings.iclr.cc/paper_files/paper/2026/file/33b47b3d2441a17b95344cd635f3dd01-Paper-Conference.pdf)).
- **Forecast aggregation:** AIA Forecaster
  ([arXiv](https://arxiv.org/html/2511.07678v1)), LEAP
  ([arXiv](https://arxiv.org/pdf/2609.01337)).
- Background: Minsky (*Society of Mind*), Rice's algorithm selection problem,
  rational metareasoning (Russell and Wefald; Lieder and Griffiths), DreamCoder,
  Darwin Gödel Machine, AlphaEvolve, GEPA, auto-sklearn, AutoGluon, Rainbow and
  MAPE-K.

**What looks open:** learned selection across genuinely different paradigms
while the agent works; a portfolio that grows by trial under a judge the agent
cannot edit; one selection interface across many decision points; evidence
that combining beats selecting.

## Open decisions (operator)

- Whether this becomes Morphogen's purpose (via `onboard`), or a new repository.
- Where trials run: needs Docker, and likely a GPU for Craftax.
- Budgets for LLM-driven episodes.
