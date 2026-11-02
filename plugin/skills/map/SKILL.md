---
name: map
description: Map a system into Morphogen's lists (systems, slots, types, sources, components) and measure its baseline. Use when the user asks what a system or target is made of, to map or inventory something, or before improving a target that has not been mapped.
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

Ids are short and stable: `targets/slow-script`, `slow-script/counting`,
`type/hash-count`, `comp/collections-counter`. References are ids.

## Steps

1. Use the `explorer` subagent to inventory the system: entry points,
   components, interfaces, and where time or cost goes. Keep only its summary.
2. Read what is already known: `lists_query` for the system and its slots.
3. Write or update entries with `lists_put`: the system, one slot per role
   that could be filled differently, the type and source of what fills each
   slot. Do not record every file; record what could be swapped.
4. If the system is a target with a `target.yaml`, call `measure` on the
   trunk to record its baseline as measured evidence.
5. Add `evidence_note` entries (trust `inferred`) for what you concluded but
   did not measure, such as "counting is the bottleneck", citing the source.
6. Report: the slots, which one limits the target and the evidence for it,
   and the baseline numbers.
