---
name: map
description: Understand a system by mapping it into Morphogen's lists - what it is for, its parts as slots, what fills each, how they connect, what is measured and what is only assumed. Works on anything (code, a service, a machine, a business process, a team, a field of research), Morphogen included. Use when the user asks what something is made of or how it works, asks to map, model or inventory something, or before improving a system that has not been mapped.
allowed-tools: Read, Glob, Grep, Agent, Bash(git:*), Bash(python:*), Bash(python3:*), mcp__plugin_morphogen_morphogen
---

# Map

Mapping is how Morphogen understands a system. A map says what the system is
for, which roles it is made of, what fills each role, how the parts connect,
and how each of those things is known. Improving the system is one thing a
map makes possible; explaining it, comparing it, finding its risks, or
deciding that nothing should change are others. Map to understand first.

Anything with parts and a purpose can be mapped: a script, a service, a
machine, a business process, a team, a supply chain, a research field,
Morphogen itself. The method is the same.

## What a map holds

| List | Entry | Refers to |
|---|---|---|
| systems | a whole with a purpose: a target, a service, an order-to-cash process, a team | its `slots`; `description` says what it is for |
| slots | a role that could be filled differently: "counting", "approval", "judge" | `system`, `accepts` (types), `filled_by` (component), `interface` |
| types | a kind of part: "hash map", "LLM call", "approver", "CRM" | — |
| sources | where parts come from: PyPI, a vendor, a staffing agency, this project | — |
| components | a specific part, with version or identity; may itself be a system | `type`, `source`, `system` |
| evidence | how each claim is known (written through tools, never by hand) | anything above |

**Slots are the point.** A slot is a role, separate from whatever fills it
today. "Counting" is a slot; a list scan is what fills it. "Credit check" is a
slot; a person, a rule engine or a vendor API might fill it. Seeing roles
apart from their fillers is what makes a system understandable and changeable.
Record what could be filled differently, not every file or person.

**A dependency is a slot filled by a component that is itself a system**
(`"system": "claude-code"` on `comp/claude-code`). Follow those links to see
what a system stands on.

**Say what each slot needs and what each part offers.** On a slot,
`requires` lists the capabilities the role needs (`exact`, `semantic`,
`temporal`, ...); on a component, `provides` lists what it offers. Then
`catalog_search` with `slot:` can propose the smallest sufficient filler, and
what a part offers beyond the need shows up as overhead.

**Patterns.** If the system follows a known architecture, look for it in a
mounted pattern library (`lists_query` on `systems` with `map: "*"` and
`pattern: true`) and record `realizes` on the system and on each slot that
plays a pattern slot. Mapping a product someone else built (interface
`observed`) is how new patterns are found: two products that realise the same
pattern differ slot by slot, and that difference is the finding.

**Say how Morphogen can reach each system** with `interface`:

- `direct`: Morphogen can act on it (code, a shell, an API it may call);
- `simulated`: it can only act on a model of it; the model is a slot of its
  own (`<system>/simulator`) and `simulates:` says what it stands for;
- `observed`: it can read it (logs, telemetry, exports) but not change it;
- `none`: it is known only from documents and interviews.

People and teams are systems too, and roles are slots. A change to one is an
assignment made through whatever system holds it (an HR, ticketing or
scheduling API), and only with the operator's approval.

Ids are short and stable: `targets/slow-script`, `slow-script/counting`,
`type/hash-count`, `comp/collections-counter`. References are ids.

## General method, domain knowledge

This skill is the method, for any system. A domain brings its own vocabulary
and access: an ontology (the types and relations that matter there, kept as
types in a mounted map) and integrations (the APIs, exports and observers that
reach its systems). Distributions add domain mapping skills that supply those
and follow this method; use their types when a map of that domain is mounted.

## How to find out

Use whichever sources the system has, and record which one each claim came
from:

- **Explore**: read code, configs, docs and logs. Use the `explorer` subagent
  so the main context gets a summary, not the raw material.
- **Interview**: ask the operator or the people who run the system. Their
  answers are `stated` evidence; note who said it.
- **Observe**: read telemetry, event logs or exports. Data collected outside
  the system is stronger than what it reports about itself.
- **Measure**: for a target with a `target.yaml`, call `measure` to record a
  baseline as `measured` evidence.

Conclusions you drew but did not check ("approval is the bottleneck") go in
with `evidence_note`, trust `inferred`, citing what they rest on.

## Worked example: the self-map

The lists start with Morphogen's map of itself: `morphogen`, `admin-ui`,
`claude-code` (the harness it runs in) and `host` (the machine). It is an
example of the shape, not the main use. Before mapping something new, read it
with `lists_query` (the `morphogen` system, then `slots` where `system` is
`morphogen`) and follow the same pattern. The `host` entries are generic;
when mapping a real machine, record what it actually has.

## Steps

1. **Purpose.** Write down what the system is for and who it serves, in one
   sentence, before listing parts. If nobody can say, that is a finding.
2. **What is already known.** `lists_query` for the system, its slots and
   anything that points at it, in this map and in mounted ones (`map: "*"`;
   the `maps` tool lists them). Do not map twice: refer to an entry in another
   map by its qualified id (`homelab:comp/gpu-box`) instead of copying it.
3. **Parts.** Explore, interview and observe. Write entries with `lists_put`:
   the system, one slot per role, the type and source of what fills each slot,
   the `interface`. Follow dependencies one level down; stop where a part is
   a system worth its own map.
4. **Evidence.** `measure` targets; `evidence_note` for what was stated or
   inferred, with its source.
5. **Report**, in this order:
   - what the system is for, and its slots;
   - how each important claim is known (measured, observed, stated,
     inferred), and the biggest gaps in that knowledge;
   - where it is limited or fragile, with the evidence;
   - which slots could be changed, and through which interface. Propose;
     changing anything is the `evolve` skill's job and the operator's call.
