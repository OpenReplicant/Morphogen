"""Minimum viable Morphogen.

Ports for lists and evidence, a files backend, and a judge that scores a
candidate commit against a base commit using the base's own harness. The MCP
server in `mcp_server` exposes these to an agent harness; the agent can ask
for a score but cannot write measured evidence or change how it is scored.
"""

__version__ = "0.1.0"
