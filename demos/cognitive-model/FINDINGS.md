# Mapping "Common Model of Cognition on Claude Code" with Morphogen

Map: `rebuild-6-map/lists/*.jsonl` (built by `rebuild-6-map/build_map.py`), mounted read-only into
a scratch Morphogen 0.3 project as `cmc`.

## The map

8 systems, 63 slots, 24 types, 5 sources, 36 components (136 entries).

- `cmc`: the whole. Slots: central selector (Claude), working memory, procedural memory,
  declarative memory, perception, motor, cycle, learning, harness, operator, evaluation.
- Each module is a system of its own:
  - `wm`: five buffers, the store, the tools, injection, decay and the compaction guard;
  - `pm`: productions, implicit (the weights), utility table, skill log, candidate ranking,
    compiled routines, pruning;
  - `dm`: store, vector index, embeddings, activation, retrieve, encode, search, core facts;
  - `percept`: senses, compression, extra senses, file watch;
  - `motor`: effectors, permissions, gate, outcome, serial bottleneck;
  - `cycle`: ten phases, in order;
  - `learn`: reward, utility update, failure credit, episodic encoding, chunking, review gate,
    consolidation, critic.

## What Morphogen found on its own

The references all resolve, and every requirement has a reason. Four capability gaps:

| Slot | Missing | Why |
|---|---|---|
| `cmc/evaluation` | paired comparison, learned-state reset, token cost | nothing fills it yet |
| `dm/vector-index` | semantic | the spec names no index |
| `pm/candidate-ranking` | semantic | ranking needs description-to-goal similarity; a hook that reads SQLite doesn't provide it |
| `learn/reward` | outside judge | the spec's own caveat: the model judges its own success |

Five slots have nothing filling them: evaluation, operator, embeddings, vector index and
compiled routines.

## Parameters

The spec sets 16 parameters but leaves 8 unset, none of which Morphogen can check yet:

- in activation: `beta`, the noise, the retrieval threshold and the source weights `W_k`;
- the failure reward;
- chunking's "high reward";
- the promote and demote thresholds.

## Spec claims checked against the Claude Code hooks reference (2026-11-03)

**Confirmed:**
- **Events:** PostToolBatch (once per batch; it can return `additionalContext`), PostToolUseFailure, FileChanged, UserPromptExpansion.
- **Hook options:** exec form, `onFailure: "block"` (Claude Code v2.1.295 or later), `async`, plugin `hooks/hooks.json`.
- **Outputs:** `updatedToolOutput` on PostToolUse, `reloadSkills` on SessionStart.
- **Stop:** `stop_hook_active` on Stop.
- **Skill matcher:** the `Skill` tool can be matched (typed `/skill` goes through UserPromptExpansion instead).

**Corrections:**
- An `additionalContext` over 10,000 characters isn't truncated. It's saved to a file, and Claude
  gets a preview of up to 2,000 characters. So the cap doesn't enforce WM capacity; the formatter
  has to.
- SessionStart matchers also include `clear` and `fork`. The design should say whether the goal
  stack survives `/clear` and forks.
- FileChanged has no decision control and can't add context. A bottom-up percept has to be
  written to the wm store and appear at the next injection. The watch list is its matcher's
  literal filenames, or `watchPaths` returned by SessionStart.
- Stop already caps continuations at 8 in a row. The spec's 2 is a stricter cap of its own, which
  is fine.

**Options the spec doesn't use:**
- `judge.js` could be a `type: "prompt"` hook on Stop. Stop supports it, so the hook needs no
  model client of its own.
- `type: "mcp_tool"` hooks can call the wm server's tools directly. They don't work for SessionStart
  at launch (the servers aren't up yet), so `boot.js` stays a command hook.

**Concurrency:** hooks run as separate processes and write the same SQLite file as the servers.
That needs WAL and a busy timeout, the problem Morphogen just fixed in its own store.

**Citation:** Laird, Lebiere and Rosenbloom (2017), "A Standard Model of the Mind", AI Magazine
38(4) 13-26, doi:10.1609/aimag.v38i4.2744. Later renamed the Common Model of Cognition.

## Where the map's shape held

- **Roles apart from fillers:** "CMC module → Claude Code primitive" is exactly "slot → component".
  Each module branched into its own system, and `follow` walks from `cmc` down to the hooks.
- **Requirements with reasons:** they turned the spec's design principles and its own caveats
  into checkable gaps.
- **Mounting:** the map lives outside the base, read-only, and refers across maps.

## Relations and parameters (after Morphogen learned them)

The map now holds 160 entries, including 24 parameters, and every relation resolves.

**Relations** (`links`):
- each buffer's `written_by` and `read_by`;
- the cycle as a chain of `next` (input → select → act → perceive → close → select);
- each module `talks_through` working memory.

`follow` walks them across maps, and Morphogen checks them like any other reference.

**Parameters:**
- 24 entries, each with an owner: the ACT-R constants are `agent` (tunable), while the review
  thresholds and the judge model are `operator`.
- Morphogen reports the 8 the spec leaves unset on its own: activation's `beta`, noise, retrieval
  threshold and `W_k`; the failure reward; chunking's "high reward"; the promote and demote thresholds.
- It also caught two missing defaults in Morphogen's own seed map (the judge's bar and its maximum
  repeats), since fixed.

## Still outside the map

Dynamics: what happens per cycle, per turn and per session, and how state moves through it. The
map records where each step sits and what follows it, not the equations as executable behaviour.
That belongs to the implementation and its tests.
