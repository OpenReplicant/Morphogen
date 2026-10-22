---
name: resolve-from-catalogs
description: Find candidate providers for an unfilled slot by searching configured catalogs (container registries, PyPI, MCP registry, private registries) from the slot's role and requirements. Use when a blueprint has unfilled slots or a parameter space needs exploring.
---
# Resolve a slot from catalogs

1. Read the slot: role, requirements, port contracts, scope.
2. Turn it into queries: keywords for registries that need them, a natural-language description for semantic search.
3. Search only **configured** registries (Milestone 2 adds the catalog search tool). Never subscribe to a new catalog; propose one instead, at the lowest trust level.
4. Score candidates: requirement coverage, contract compatibility, license, maintenance, signatures and provenance, source trust.
5. Return the top candidates as hypothetical type-level providers with reasons. Gaps with no candidate become a build task.
6. Candidates × configuration options form an experiment matrix; each is tested in sandbox through a proposal.
