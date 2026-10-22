---
name: design-system
description: Model an existing or imagined system as Morphogen slots and couplings and produce a blueprint.submitted event. Use when someone describes a system, asks to blueprint one, or wants to map something that has no telemetry.
---
# Design a system

1. **Elicit.** Purpose; the roles involved (slots, not containers); what each needs (requirements) and offers (capabilities); interfaces (ports, with contracts if known); constraints. Reuse a domain vocabulary if one fits.
2. **Draft** slots, ports and couplings. Coupling type is one of call, event, stream, shared_state, request_reply. Nested parts use `parent`.
3. **Show** the draft as a table and ask for corrections. Each correction replaces the draft; do not argue with the person's knowledge of their system.
4. **Check** before submitting:
   - every coupling joins existing `slot.port` names;
   - every slot has at least one port;
   - list unfilled slots (no provider hint) and couplings without contracts as open items.
5. **Submit** only after confirmation: an event matching `schemas/events/blueprint-submitted.schema.json`, type `org.openreplicant.morphogen.blueprint.submitted`, status hypothetical. Example: `examples/self-blueprint.json`.

Statements a person makes about an existing system are `asserted`, low confidence, until observed.
