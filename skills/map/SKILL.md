---
name: map
description: Map a system into Morphogen's lists (systems, slots, types, sources, components) and measure its baseline. Use when the user asks what a system or target is made of, to map or inventory something, or before improving a target that has not been mapped.
allowed-tools: Read, Glob, Grep, Agent, Bash(git:*), Bash(python:*), Bash(python3:*), mcp__plugin_morphogen_morphogen
---

# Map

Describe a system as lists, then measure it. The lists are what Morphogen
knows; keep them true and small.

## The six lists

| List | Entry | Refers to |
|---|---|---|
| systems | a whole: a target, a service, Morphogen itself | its `slots` |
| slots | a role in a system: "counting", "parser", "judge" | `system`, `accepts` (types), `filled_by` (component), `interface` |
| types | a kind of component: "hash map", "regex", "LLM call" | — |
| sources | where parts come from: PyPI, the standard library, this project | — |
| components | a specific part, with version | `type`, `source`; may itself be a system |
| evidence | claims with support (written through tools, never by hand) | anything above |

Record how Morphogen can act on each system: `interface: direct` when there is
an API, a shell or code it can change; `interface: simulated` when it can only
act on a model, with the model as a slot of its own (`<system>/simulator`) and
`simulates:` saying what it stands for. People and teams are systems too, and
roles are slots; a swap is an assignment made through whatever system holds
it (an HR, ticketing or scheduling API), and only with the operator's approval.

Ids are short and stable: `targets/slow-script`, `slow-script/counting`,
`type/hash-count`, `comp/collections-counter`. References are ids.

## Worked example: the self-map

The lists start with three mapped systems: `morphogen`, `claude-code` (the
harness it runs in) and `host` (the machine). Before mapping something new,
read one with `lists_query` (the `morphogen` system, then `slots` where
`system` is `morphogen`) and copy its shape. A dependency is a slot filled by
a component that is itself a system: `morphogen/harness` is filled by
`comp/claude-code`, whose `system` is `claude-code`. The `host` entries are
generic; when mapping this machine, replace them with what it actually has.

## Steps

1. Use the `explorer` subagent to inventory the system: entry points,
   components, interfaces, and where time or cost goes. Keep only its summary.
2. Read what is already known: `lists_query` for the system and its slots.
   If the system is new, follow the shape of the self-map above.
3. Write or update entries with `lists_put`: the system, one slot per role
   that could be filled differently, the type and source of what fills each
   slot. Do not record every file; record what could be swapped.
4. If the system is a target with a `target.yaml`, call `measure` on the
   trunk to record its baseline as measured evidence.
5. Add `evidence_note` entries (trust `inferred`) for what you concluded but
   did not measure, such as "counting is the bottleneck", citing the source.
6. Report: the slots, which one limits the target and the evidence for it,
   and the baseline numbers.
