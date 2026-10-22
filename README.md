# Morphogen

An [OpenReplicant](https://github.com/OpenReplicant) project.

Map any system as slots and couplings, close a MAPE-K loop over the map, and grow by filling slots from catalogs or by building and testing new providers. The first target is the system itself.

- Architecture: [docs/architecture.md](docs/architecture.md) (live, canonical version: the "System Mapping and Adaptation Architecture" doc)
- Plan: [docs/plan.md](docs/plan.md)
- Decisions: [docs/decisions/](docs/decisions/)
- Agent rules: [AGENTS.md](AGENTS.md)

## Layout

| Path | Contents |
| --- | --- |
| `src/morphogen/` | Intake, ingestors, watchers, domain layer, map MCP server |
| `schemas/` | Event schemas, ontology shapes |
| `contracts/` | AsyncAPI for the intake |
| `deploy/` | Compose, Caddy, OTel Collector, Postgres init |
| `ui/` | Alpine.js + daisyUI window-manager shell |
| `intent/` | Desired state the orchestrators reconcile (written only by the promoter) |
| `plugins/morphogen/` | Claude Code plugin for agents operating on targets |
| `.claude/` | Development tooling for working on this repo |

## License

Apache-2.0. See `LICENSE`.
