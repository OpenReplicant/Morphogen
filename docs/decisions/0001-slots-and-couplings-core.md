# 0001 Slots and couplings as the core model

Status: accepted · 2026-10-22

**Decision.** The core ontology models systems composed of slots and couplings, not "anything whatsoever." Couplings are nodes, not edges. Requirements/capabilities (TOSCA) generate coupling candidates. Domain vocabularies extend the core.

**Why.** A small core with strict domain vocabularies constrains reasoning; universal ontologies (UML-style) stop constraining anything. Couplings need their own type, contract, observations and history, which edges cannot carry cleanly.

**Consequences.** Slots are roles, not containers: a slot can be filled by a service, API, MCP server, device, person or model call. Providers may themselves be slot graphs (recursion).
