# Setting up Claude Code (and other harnesses)

## Developing this repo

1. `uv sync`, then `docker compose -f deploy/docker-compose.yml up -d`.
2. Open the repo in Claude Code. `CLAUDE.md` loads automatically; approve the project MCP server `morphogen-map` (`.mcp.json`).
3. Project memory for the dev session (optional), in its **own** dataset, never `map`:
   ```
   claude plugin marketplace add topoteretes/cognee-integrations
   claude plugin install cognee-memory@cognee
   ```
   Point it at a dataset named `agent-memory-claude-code-dev`. Check the plugin's current configuration options in cognee's docs.
4. Dev telemetry: `.claude/settings.json` exports Claude Code's OpenTelemetry to the local Collector, so dev sessions show up as observations of the system.

Tooling here: `invariant-reviewer` subagent, `/adr` skill, schema check hook.

## Agents operating on targets (Claude Code)

Install the plugin from this repo:
```
claude plugin marketplace add OpenReplicant/morphogen
claude plugin install morphogen@morphogen
```
Set `MORPHOGEN_HOME` (repo path or installed package), `MORPHOGEN_INTAKE_URL`, `MORPHOGEN_TARGET`, `MORPHOGEN_AGENT_ID`. The plugin brings the designer, analyzer, planner and verifier subagents, five skills, the guard hooks and the `morphogen-map` MCP server. Add cognee-memory pointed at `agent-memory-<agent-id>`.

A marketplace manifest (`.claude-plugin/marketplace.json` at the repo root) is needed for the install command above; add it when publishing.

## Other harnesses (Codex, Cursor, Agent SDK, …)

- Register the `morphogen-map` MCP server (stdio: `uv run python -m morphogen.mcp.server`).
- Give the agent `AGENTS.md` as its rules file.
- Use the skills in `plugins/morphogen/skills/` as procedure documents.
- For memory, use cognee's MCP server (`remember` / `recall`) on the agent's own dataset.
- Enforce isolation in the container (no intent write, no credentials); hooks are Claude Code–specific conveniences.
