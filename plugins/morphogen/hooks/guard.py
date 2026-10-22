"""PreToolUse guard: block writes to intent/, the map, and orchestrator commands.

A convenience layer only. The real boundary is the container: agents run
without intent write access or orchestrator credentials (decision 0008).
Exit code 2 blocks the tool call and shows the reason to the model.
"""

import json
import re
import sys

BLOCKED_PATHS = re.compile(r"(^|/)(intent/|\.?morphogen/policies/|approvals/)")
BLOCKED_COMMANDS = re.compile(
    r"\b(docker\s+(compose\s+)?(up|run|rm|stop|kill)|kubectl\s+(apply|delete|scale|edit|patch)|"
    r"nomad\s+job\s+(run|stop)|psql\b|git\s+push)"
)

event = json.load(sys.stdin)
tool = event.get("tool_name", "")
args = event.get("tool_input", {}) or {}

if tool in ("Write", "Edit", "MultiEdit"):
    path = args.get("file_path", "")
    if BLOCKED_PATHS.search(path):
        print(f"Blocked: {path} is written only by the promoter. Use morphogen-map.propose.", file=sys.stderr)
        sys.exit(2)

if tool == "Bash":
    cmd = args.get("command", "")
    if BLOCKED_COMMANDS.search(cmd):
        print("Blocked: agents do not act on orchestrators or the database. Use morphogen-map.propose.", file=sys.stderr)
        sys.exit(2)

sys.exit(0)
