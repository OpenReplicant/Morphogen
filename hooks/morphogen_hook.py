"""Claude Code hooks for Morphogen. Standard library only.

    session  print a short briefing (or a setup hint) at session start
    pre      stop tool calls once the session's budget is spent (if one is set)
    post     append a trace line per tool call

Does nothing in projects without a morphogen.yaml, apart from the setup hint.
"""

import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd())
CFG_FILE = ROOT / "morphogen.yaml"


def setting(text, key, default):
    m = re.search(rf"^\s*{key}:\s*([^\s#]+)", text, re.M)
    return m.group(1) if m else default


def read_stdin():
    try:
        return json.load(sys.stdin)
    except (ValueError, OSError):
        return {}


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def evidence_summary(path):
    if not path.exists():
        return 0, "intact", None
    prev, last_verdict, n = "0" * 64, None, 0
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        n += 1
        rec = json.loads(line)
        body = {k: v for k, v in rec.items() if k != "hash"}
        if rec.get("prev") != prev or hashlib.sha256(canonical(body).encode()).hexdigest() != rec.get("hash"):
            return n, f"BROKEN at record {n}", last_verdict
        prev = rec["hash"]
        if rec.get("kind") == "verdict":
            last_verdict = rec
    return n, "intact", last_verdict


def evidence_file(cfg_text):
    """Same rule as the server: git's common directory, else the data directory."""
    import subprocess
    explicit = setting(cfg_text, "evidence_path", "")
    if explicit:
        return ROOT / explicit
    try:
        p = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=ROOT, capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            common = Path(p.stdout.strip())
            return (common if common.is_absolute() else ROOT / common).resolve() / "morphogen" / "evidence.jsonl"
    except OSError:
        pass
    return ROOT / setting(cfg_text, "data_dir", ".morphogen") / "evidence.jsonl"


def session(cfg_text):
    if not cfg_text:
        print("Morphogen is installed but not set up in this project. To start: /morphogen:onboard")
        return
    data = ROOT / setting(cfg_text, "data_dir", ".morphogen")
    n, chain, verdict = evidence_summary(evidence_file(cfg_text))
    targets = re.findall(r"^\s*-\s*(\S+)", cfg_text.split("targets:", 1)[1], re.M) if "targets:" in cfg_text else []
    lines = [
        f"Morphogen: autonomy {setting(cfg_text, 'autonomy', '2')}, trunk {setting(cfg_text, 'trunk', 'main')}, "
        f"targets {', '.join(targets) or 'none'}.",
        f"Evidence: {n} records, chain {chain}.",
    ]
    if verdict:
        lines.append(f"Last verdict: {verdict.get('claim')} ({verdict.get('verdict')}).")
    journal = evidence_file(cfg_text).parent / "journal.jsonl"  # beside the evidence log (files backend)
    if journal.exists():
        last = [l for l in journal.read_text().splitlines() if l.strip()][-1:]
        if last:
            try:
                lines.append(f"Last journal entry: {json.loads(last[0]).get('title')}.")
            except ValueError:
                pass
    lines.append("Skills: /morphogen:map, /morphogen:evolve, /morphogen:playbook. The judge is the morphogen MCP server.")
    print("\n".join(lines))


def traces_path(cfg_text):
    return ROOT / setting(cfg_text, "data_dir", ".morphogen") / "traces.jsonl"


def pre(cfg_text, event):
    budget = int(setting(cfg_text, "tool_calls", "0") or 0)
    if not budget:
        return 0
    p, sid, used = traces_path(cfg_text), event.get("session_id"), 0
    if p.exists():
        used = sum(1 for l in p.read_text().splitlines() if f'"session":"{sid}"' in l)
    if used >= budget:
        print(f"Morphogen: this session's tool-call budget ({budget}) is spent. "
              "The operator can raise budget.tool_calls in morphogen.yaml.", file=sys.stderr)
        return 2
    return 0


def post(cfg_text, event):
    p = traces_path(cfg_text)
    p.parent.mkdir(parents=True, exist_ok=True)
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "session": event.get("session_id"),
           "tool": event.get("tool_name")}
    with p.open("a") as f:
        f.write(canonical(rec) + "\n")
    return 0


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ""
    cfg_text = CFG_FILE.read_text() if CFG_FILE.exists() else ""
    event = read_stdin() if mode in ("pre", "post") else {}
    if mode == "session":
        session(cfg_text)
        return 0
    if not cfg_text:
        return 0
    if mode == "pre":
        return pre(cfg_text, event)
    if mode == "post":
        return post(cfg_text, event)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # a broken hook must not block the session
        print(f"Morphogen hook error: {e}", file=sys.stderr)
        sys.exit(0)
