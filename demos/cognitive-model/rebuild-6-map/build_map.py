"""Map "Common Model of Cognition on Claude Code" (spec, 2026-11-01) into Morphogen's lists.

Writes JSONL to ../.morphogen/lists, the format a distribution publishes and mounts.
Fields beyond Morphogen's (params, phase, order, writes, reads, cmc_module) are kept as-is:
the lists keep unknown keys. The findings at the end of the report say which of them the
base can check and which it can't.
"""

import json
import sys
from pathlib import Path

OUT = Path(sys.argv[1])
systems, slots, types, sources, components = [], [], [], [], []
DOC = "https://code.claude.com/docs/en/hooks.md"


def system(id, description, slot_ids, **kw):
    systems.append({"id": id, "description": description, "slots": slot_ids, "interface": "direct", **kw})


OWNER = {"decay_d": "agent", "beta": "agent", "noise": "agent", "retrieval_threshold": "agent", "W_k": "agent",
         "alpha": "agent", "utility_start": "agent", "candidates": "agent", "evict_after_cycles": "agent",
         "snapshot_chars": "agent", "failure_reward": "agent", "high_reward": "agent", "min_repeats": "agent",
         "prune_below": "operator", "min_fires": "operator", "promote_threshold": "operator",
         "demote_threshold": "operator", "max_continuations": "operator", "judge_model": "operator"}


def slot(id, system, accepts, interface, filled_by=None, params=None, **kw):
    for k, v in (params or {}).items():
        param(f"{id.replace('/', '-')}-{k.replace('_', '-')}".lower(), id, type(v).__name__ if v is not None else "float",
              v, OWNER[k], "spec")
    e = {"id": id, "system": system, "accepts": accepts, "interface": interface, **kw}
    if filled_by:
        e["filled_by"] = filled_by
    slots.append(e)


parameters = []


def param(pid, of, typ, value, owner, set_in, rng=None, description=None):
    e = {"id": f"param/{pid}", "of": of, "type": typ, "owner": owner, "set_in": set_in}
    if value is not None:
        e["value"] = value
    if rng is not None:
        e["range"] = rng
    if description:
        e["description"] = description
    parameters.append(e)


def comp(id, type, source, status="planned", **kw):
    components.append({"id": id, "type": type, "source": source, "status": status, **kw})


# --- types and sources
for t, d in [
    ("type/agent-harness", "Runs the top-level LLM loop with tools and skills"),
    ("type/llm", "A language model"),
    ("type/mcp-server", "A stdio MCP server the harness starts"),
    ("type/hook-command", "A command hook (exec form) on a lifecycle event"),
    ("type/hook-prompt", "A prompt hook: an LLM evaluates the event"),
    ("type/hook-mcp-tool", "A hook that calls an MCP server's tool"),
    ("type/skill", "A SKILL.md: description is the condition, body the action (a production)"),
    ("type/subagent", "A delegated agent with its own context and tools"),
    ("type/builtin-tool", "A harness tool (Read, Grep, Edit, Bash, ...)"),
    ("type/sqlite-table", "A table in the project's .cmc/cmc.sqlite"),
    ("type/vector-index", "Nearest-neighbour search over embeddings"),
    ("type/embedding-model", "Turns text into vectors for similarity"),
    ("type/instructions-file", "A file the harness loads into every session (CLAUDE.md)"),
    ("type/permission-rules", "Allow and deny rules in settings.json"),
    ("type/folder", "A directory used as a queue or state (proposed, inactive skills)"),
    ("type/person", "A person in a role"),
    ("type/task-suite", "Recurring tasks run with and without the system"),
]:
    types.append({"id": t, "description": d})
for s, n, f, u in [
    ("src/anthropic", "Anthropic", "Claude Code and Claude models", "https://code.claude.com"),
    ("src/cmc-plugin", "The cmc plugin", "components built for this design", None),
    ("src/act-r", "ACT-R and Soar literature", "buffer, activation, utility and chunking equations", None),
    ("src/sqlite", "SQLite", "the embedded database", "https://sqlite.org"),
    ("src/operator", "The operator", "review and approval", None),
]:
    sources.append({"id": s, "name": n, "finds": f, **({"url": u} if u else {})})

# --- the whole
system("cmc", "Common Model of Cognition on Claude Code: Claude is the central pattern matcher and action "
       "selector; the plugin supplies a small working memory, separate procedural and declarative stores, "
       "quantitative metadata, and learning as a side effect of work",
       ["cmc/central-selector", "cmc/working-memory", "cmc/procedural-memory", "cmc/declarative-memory",
        "cmc/perception", "cmc/motor", "cmc/cycle", "cmc/learning", "cmc/harness", "cmc/operator",
        "cmc/evaluation"],
       principles=["working memory is the only hub", "symbols plus numbers",
                   "hooks are the architecture; prompts are the content", "learning is online and gated"],
       theory="Laird, Lebiere and Rosenbloom (2017), A Standard Model of the Mind, AI Magazine 38(4) 13-26")
slot("cmc/central-selector", "cmc", ["type/llm"], "reads the WM snapshot, matches productions, selects one act per cycle",
     "comp/session-model", cmc_module="central pattern matcher")
slot("cmc/harness", "cmc", ["type/agent-harness"], "hooks, skills, subagents, MCP client, permissions", "comp/claude-code")
slot("cmc/operator", "cmc", ["type/person"], "promotes proposed skills; gives explicit feedback that outweighs the judge")
for mod, sysid, desc in [
    ("working-memory", "wm", "A small, slot-based workspace re-injected into context every cycle; the only hub"),
    ("procedural-memory", "pm", "Productions (skills, subagents, the model's weights) with utilities"),
    ("declarative-memory", "dm", "Semantic and episodic chunks, retrieved one at a time by activation"),
    ("perception", "percept", "Read-side tools and watchers, compressed into the percept buffer"),
    ("motor", "motor", "Write-side tools, gated on a stated goal"),
    ("cycle", "cycle", "One model step between tool batches; hooks run each phase"),
    ("learning", "learn", "Reinforcement, encoding, chunking and consolidation as side effects of work"),
]:
    slot(f"cmc/{mod}", "cmc", [f"type/cmc-{sysid}"], desc, f"comp/cmc-{sysid}", cmc_module=mod.replace("-", " "),
         links={"talks_through": "cmc/working-memory"} if mod != "working-memory" else {})
    types.append({"id": f"type/cmc-{sysid}", "description": desc})
    comp(f"comp/cmc-{sysid}", f"type/cmc-{sysid}", "src/cmc-plugin", system=sysid)
slot("cmc/evaluation", "cmc", ["type/task-suite"], "20 recurring tasks over 2 weeks, with and without cmc: success rate, "
     "tokens per task, how often the same mistake repeats", requires=["paired-comparison", "learned-state-reset",
     "token-cost"], because={"paired-comparison": "spec, build step 6: with and without cmc",
     "learned-state-reset": "cmc learns across sessions; each arm must start from a known memory state",
     "token-cost": "spec metric: tokens per task"})

# --- working memory
BUFS = [("goal", "current goal and subgoal stack", "Claude via wm_set_goal, wm_push_subgoal, wm_pop_subgoal", 1),
        ("percept", "latest compressed perception", "percept server, perceive hook", 1),
        ("retrieval", "last chunk returned from declarative memory", "dm_retrieve", 1),
        ("imaginal", "scratch problem state (plan, partial answer)", "Claude via wm_put", 5),
        ("motor", "last action and its outcome", "motor-outcome hook", 1)]
system("wm", "Working memory: named buffers, each holding at most one chunk (imaginal up to 5)",
       [f"wm/buffer-{b}" for b, *_ in BUFS] + ["wm/store", "wm/tools", "wm/injection", "wm/decay", "wm/compaction-guard"])
WRITERS = {"goal": ["cmc/central-selector"], "percept": ["comp/percept-server", "comp/hook-perceive"],
           "retrieval": ["dm/retrieve", "learn/critic"], "imaginal": ["cmc/central-selector"],
           "motor": ["comp/hook-motor-outcome"]}
for b, holds, writer, cap in BUFS:
    slot(f"wm/buffer-{b}", "wm", ["type/sqlite-table"], f"holds {holds}", "comp/wm-buffers-table",
         links={"written_by": WRITERS[b], "read_by": ["wm/injection"]})
    param(f"wm-{b}-capacity", f"wm/buffer-{b}", "int", cap, "operator", "spec: Buffers", rng=[1, 10])
slot("wm/store", "wm", ["type/mcp-server"], "buffers, goal stack and the procedures table in .cmc/cmc.sqlite",
     "comp/wm-server", requires=["concurrent-writers"],
     because={"concurrent-writers": "hooks (separate processes) and the wm server write the same SQLite file"})
slot("wm/tools", "wm", ["type/mcp-server"], "wm_get, wm_put(buffer, chunk), wm_set_goal, wm_push_subgoal, "
     "wm_pop_subgoal, wm_clear(buffer)", "comp/wm-server")
slot("wm/injection", "wm", ["type/hook-command"], "snapshot as additionalContext at the start of every cycle, ~2,000 "
     "characters", "comp/hook-inject-wm", requires=["context-every-cycle"],
     because={"context-every-cycle": "principle: WM is the hub, re-injected each cycle"},
     params={"snapshot_chars": 2000})
slot("wm/decay", "wm", ["type/hook-command"], "evict chunks untouched for N cycles and hand them to the encoder",
     "comp/hook-close-cycle", params={"evict_after_cycles": 8})
slot("wm/compaction-guard", "wm", ["type/hook-command"], "flush WM and the goal stack to dm before compaction; "
     "re-inject after", "comp/hook-flush-wm", requires=["survives-compaction"],
     because={"survives-compaction": "build step 1 is done when a goal stack survives /compact and --resume"})

# --- procedural memory
system("pm", "Procedural memory: skills as explicit productions over the model's implicit procedures",
       ["pm/productions", "pm/implicit", "pm/utility-table", "pm/skill-log", "pm/candidate-ranking",
        "pm/compiled-routines", "pm/pruning"])
slot("pm/productions", "pm", ["type/skill"], "condition names WM buffers; every action step ends by changing WM",
     "comp/project-skills")
slot("pm/implicit", "pm", ["type/llm"], "the model's weights: most procedural knowledge", "comp/session-model")
slot("pm/utility-table", "pm", ["type/sqlite-table"], "per skill: utility (0..1, starts 0.5), fires, successes, "
     "last_fired", "comp/wm-procedures-table", params={"utility_start": 0.5})
slot("pm/skill-log", "pm", ["type/hook-command"], "log which skill fired this cycle", "comp/hook-log-skill",
     requires=["sees-skill-calls"], because={"sees-skill-calls": "utility credit needs the skills that fired"})
slot("pm/candidate-ranking", "pm", ["type/hook-command"], "top 3 skills by similarity(description, goal) x utility, "
     "added to the WM snapshot", "comp/hook-inject-wm", requires=["semantic"],
     because={"semantic": "ranking uses similarity between a skill's description and the goal"},
     params={"candidates": 3})
slot("pm/compiled-routines", "pm", ["type/subagent"], "long self-contained procedures; return one chunk to the "
     "retrieval or imaginal buffer")
slot("pm/pruning", "pm", ["type/subagent"], "move skills with utility < 0.2 after >= 10 fires to _inactive/, then "
     "reloadSkills", "comp/agent-consolidator", params={"prune_below": 0.2, "min_fires": 10})

# --- declarative memory
system("dm", "Declarative memory: semantic and episodic chunks; one best chunk per cue, by activation",
       ["dm/store", "dm/vector-index", "dm/embeddings", "dm/activation", "dm/retrieve", "dm/encode", "dm/search",
        "dm/core-facts"])
slot("dm/store", "dm", ["type/sqlite-table"], "chunk: id, kind, slots (JSON), text, embedding, created, "
     "access_times[], source", "comp/dm-chunks-table")
slot("dm/vector-index", "dm", ["type/vector-index"], "nearest chunks to a cue", requires=["semantic"],
     because={"semantic": "activation's third term: embedding similarity to the cue"},
     notes="the spec names no index")
slot("dm/embeddings", "dm", ["type/embedding-model"], "embed chunks and cues", notes="the spec names no model")
slot("dm/activation", "dm", ["type/mcp-server"], "A_i = ln(sum t_j^-d) + sum W_k S_ki + beta sim(cue,i) + noise; "
     "below threshold returns failure", "comp/dm-server",
     params={"decay_d": 0.5, "beta": None, "noise": None, "retrieval_threshold": None, "W_k": None},
     notes="beta, noise, threshold and source weights are not given")
slot("dm/retrieve", "dm", ["type/mcp-server"], "dm_retrieve(cue, kind?) -> one chunk into the retrieval buffer; "
     "appends the time to access_times (rehearsal)", "comp/dm-server")
slot("dm/encode", "dm", ["type/mcp-server"], "dm_encode(chunk)", "comp/dm-server")
slot("dm/search", "dm", ["type/mcp-server"], "dm_search(query, k): debugging only; denied to Claude in settings",
     "comp/dm-server")
slot("dm/core-facts", "dm", ["type/instructions-file"], "high-activation facts always loaded; promoted and demoted "
     "by the consolidator", "comp/project-claude-md")

# --- perception and motor
system("percept", "Perception: senses feed the percept buffer, compressed",
       ["percept/senses", "percept/compress", "percept/extra-senses", "percept/watch"])
slot("percept/senses", "percept", ["type/builtin-tool"], "Read, Grep, Glob, WebFetch, WebSearch, read-only MCP servers",
     "comp/claude-code-read-tools")
slot("percept/compress", "percept", ["type/hook-command"], "compress large results into a percept chunk; may replace "
     "the result with updatedToolOutput", "comp/hook-perceive", requires=["replace-tool-output"],
     because={"replace-tool-output": "perceptual filtering"})
slot("percept/extra-senses", "percept", ["type/mcp-server"], "log tail, CI status poller, screenshot description",
     "comp/percept-server")
slot("percept/watch", "percept", ["type/hook-command"], "bottom-up percepts when watched files change",
     "comp/hook-file-changed")
system("motor", "Motor: write-side tools are the only way to change the world",
       ["motor/effectors", "motor/permissions", "motor/gate", "motor/outcome", "motor/serial-bottleneck"])
slot("motor/effectors", "motor", ["type/builtin-tool", "type/mcp-server"], "Edit, Write, Bash, actuator MCP tools",
     "comp/claude-code-write-tools")
slot("motor/permissions", "motor", ["type/permission-rules"], "which effectors run without asking",
     "comp/project-settings")
slot("motor/gate", "motor", ["type/hook-command"], "deny a motor tool when the goal buffer is empty",
     "comp/hook-gate-motor", requires=["fail-closed"],
     because={"fail-closed": "a crashed gate must never let an action through"})
slot("motor/outcome", "motor", ["type/hook-command"], "write the action and outcome to the motor buffer",
     "comp/hook-motor-outcome")
slot("motor/serial-bottleneck", "motor", ["type/instructions-file", "type/hook-command"], "one intention per batch; "
     "optionally deny a second motor tool in a batch", "comp/project-claude-md",
     notes="soft: an instruction plus an optional check")

# --- the cycle: phases in order
PHASES = [("boot", "SessionStart", "startup|resume|compact", "comp/hook-boot",
           "restore the goal stack from dm; inject WM and the active skills"),
          ("input", "UserPromptSubmit", None, "comp/hook-inject-wm", "prompt as percept; set goal; inject WM and "
           "top-3 candidates"),
          ("select", None, None, "comp/session-model", "Claude matches skills against WM and chooses one act"),
          ("act", "PreToolUse", "Edit|Write|Bash", "comp/hook-gate-motor", "gate motor tools; log the selection"),
          ("perceive", "PostToolUse, PostToolUseFailure", None, "comp/hook-perceive", "compress results; motor "
           "outcome; log fired skill"),
          ("close", "PostToolBatch", None, "comp/hook-close-cycle", "decay and evict; tick the cycle; re-inject WM"),
          ("turn-end", "Stop", None, "comp/hook-judge", "judge the goal; record reward; continue if a subgoal is open"),
          ("encode", "Stop (async)", None, "comp/hook-encode-episode", "encode the turn as an episodic chunk"),
          ("pre-compact", "PreCompact", None, "comp/hook-flush-wm", "flush WM and the goal stack to dm"),
          ("session-end", "SessionEnd", None, "comp/hook-queue-learning", "queue consolidation and chunking")]
system("cycle", "The cognitive cycle: one model step between tool batches", [f"cycle/{p[0]}" for p in PHASES])
NEXT = {"input": "select", "select": "act", "act": "perceive", "perceive": "close", "close": "select",
        "boot": "input", "turn-end": "encode", "pre-compact": "boot", "encode": "session-end"}
for i, (p, event, matcher, filler, what) in enumerate(PHASES, start=1):
    slot(f"cycle/{p}", "cycle", ["type/llm"] if p == "select" else ["type/hook-command"], what, filler,
         event=event, **({"matcher": matcher} if matcher else {}),
         **({"links": {"next": f"cycle/{NEXT[p]}"}} if p in NEXT else {}))

# --- learning
system("learn", "Learning: online and gated", ["learn/reward", "learn/utility-update", "learn/failure-credit",
       "learn/episodic-encoding", "learn/chunking", "learn/review-gate", "learn/consolidation", "learn/critic"])
slot("learn/reward", "learn", ["type/hook-command", "type/hook-prompt"], "R in [0,1] from goal outcome, tests passing "
     "and explicit feedback; at most 2 continuations per turn", "comp/hook-judge", requires=["outside-judge"],
     because={"outside-judge": "spec's own limit: a model judging its own success gives biased credit"},
     params={"max_continuations": 2, "judge_model": "claude-haiku-5-5"})
slot("learn/utility-update", "learn", ["type/sqlite-table"], "U_i <- U_i + alpha (R - U_i) for every skill fired "
     "this turn", "comp/wm-procedures-table", params={"alpha": 0.2})
slot("learn/failure-credit", "learn", ["type/hook-command"], "small negative reward to the active skill on "
     "PostToolUseFailure", "comp/hook-motor-outcome", params={"failure_reward": None},
     notes="the size of the negative reward is not given")
slot("learn/episodic-encoding", "learn", ["type/hook-command"], "goal, skills fired, key percepts, outcome, reward; "
     "also evicted WM chunks", "comp/hook-encode-episode")
slot("learn/chunking", "learn", ["type/subagent"], "draft a skill from a tool sequence that recurred >= 3 times with "
     "high reward, into _proposed/ with an evidence note", "comp/agent-chunker",
     params={"min_repeats": 3, "high_reward": None})
slot("learn/review-gate", "learn", ["type/person", "type/folder"], "a person moves drafts from _proposed/ to skills/",
     "comp/proposed-folder")
slot("learn/consolidation", "learn", ["type/subagent"], "merge duplicate chunks; promote and demote CLAUDE.md "
     "facts; prune skills", "comp/agent-consolidator", params={"promote_threshold": None, "demote_threshold": None})
slot("learn/critic", "learn", ["type/subagent"], "after low reward twice in a row; writes the retrieval buffer",
     "comp/agent-critic", notes="a narrow stand-in for metacognition")

# --- components
comp("comp/claude-code", "type/agent-harness", "src/anthropic", "in use", version="2.1.295 or later (onFailure)")
comp("comp/session-model", "type/llm", "src/anthropic", "in use")
comp("comp/claude-code-read-tools", "type/builtin-tool", "src/anthropic", "in use")
comp("comp/claude-code-write-tools", "type/builtin-tool", "src/anthropic", "in use")
comp("comp/project-settings", "type/permission-rules", "src/cmc-plugin",
     allow=["mcp__plugin_cmc_wm", "mcp__plugin_cmc_dm__dm_retrieve", "mcp__plugin_cmc_dm__dm_encode",
            "mcp__plugin_cmc_percept", "Read", "Grep", "Glob"], deny=["mcp__plugin_cmc_dm__dm_search"])
comp("comp/project-claude-md", "type/instructions-file", "src/cmc-plugin")
comp("comp/project-skills", "type/skill", "src/cmc-plugin", path=".claude/skills/")
comp("comp/proposed-folder", "type/folder", "src/cmc-plugin", path=".claude/skills/_proposed/")
for name, desc in [("wm", "buffers, goal stack, procedures"), ("dm", "chunks, activation, retrieval"),
                   ("percept", "extra senses")]:
    comp(f"comp/{name}-server", "type/mcp-server", "src/cmc-plugin", language="node", notes=desc,
         provides=["concurrent-writers"] if name == "wm" else [])
comp("comp/wm-buffers-table", "type/sqlite-table", "src/sqlite")
comp("comp/wm-procedures-table", "type/sqlite-table", "src/sqlite")
comp("comp/dm-chunks-table", "type/sqlite-table", "src/sqlite")
HOOK_PROVIDES = {"inject-wm": ["context-every-cycle"], "close-cycle": ["context-every-cycle"],
                 "gate-motor": ["fail-closed"], "perceive": ["replace-tool-output"], "log-skill": ["sees-skill-calls"],
                 "flush-wm": ["survives-compaction"], "boot": ["survives-compaction"], "judge": []}
for h in ["boot", "inject-wm", "gate-motor", "perceive", "log-skill", "motor-outcome", "close-cycle", "judge",
          "encode-episode", "flush-wm", "queue-learning", "file-changed"]:
    comp(f"comp/hook-{h}", "type/hook-command", "src/cmc-plugin", script=f"hooks/{h}.js",
         provides=HOOK_PROVIDES.get(h, []))
for a in ["chunker", "consolidator", "critic"]:
    comp(f"comp/agent-{a}", "type/subagent", "src/cmc-plugin", card=f"agents/{a}.md")

for kind, rows in [("systems", systems), ("slots", slots), ("types", types), ("sources", sources),
                   ("components", components), ("parameters", parameters)]:
    (OUT / f"{kind}.jsonl").write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in sorted(rows, key=lambda r: r["id"])))
print({k: len(v) for k, v in [("systems", systems), ("slots", slots), ("types", types), ("sources", sources),
                               ("components", components), ("parameters", parameters)]})
