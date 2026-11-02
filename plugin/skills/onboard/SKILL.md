---
name: onboard
description: Set Morphogen up in a project and agree its intent with the operator. Use when the user says "set up Morphogen", "onboard", "start Morphogen here", or when the session briefing says Morphogen is not set up.
allowed-tools: Read, Glob, Grep, Write, Edit, Bash(git:*), mcp__plugin_morphogen_morphogen
---

# Onboard

Set the project up, then write down with the operator what Morphogen is for
here. Do not start improving anything in this skill.

## Steps

1. Call the morphogen MCP server's `doctor` tool. Report in two or three
   lines: git and trunk status, backend, evidence chain, sandbox, and which
   guarantees are not active (for example, no Docker means trials run
   directly on this machine).
2. If there is no `morphogen.yaml`, call `init_project`. It writes
   `morphogen.yaml`, `catalogs.yaml`, the data directory and seed lists that
   map Morphogen itself.
3. Interview the operator, one short question at a time, and skip anything
   already answered:
   - What should Morphogen improve here, and what counts as better?
   - What must never get worse (correctness, latency, cost)? These become the
     constraints the judge holds.
   - Autonomy: 1 assist, 2 propose (every merge needs the operator), 3 merge
     free changes, 4 autonomous. Default 2.
   - Budgets: tool calls per session, trials per day. Sandbox: Docker or none.
4. Draft `intent.md` (purpose, goals and constraints, hard limits) using
   `samples/intent.example.md` in the plugin directory (`doctor` reports it
   as `plugin_root`) as the shape, and update
   `morphogen.yaml`. Show both to the operator. The operator owns these files:
   change them only with their approval.
5. If the operator has no target yet, offer the sample: `install_sample`
   with name `slow-script` copies a correct but slow script with its judge
   harness into `targets/slow-script`.
6. Commit the setup on the trunk only if the operator approves; otherwise
   leave it for them to commit.
7. Suggest the next step: `/morphogen:map` for the target, then
   `/morphogen:evolve`.
