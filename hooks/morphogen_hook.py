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


def database_file(cfg_text):
    """Same rule as the server (config.sqlite_path): git's common
    directory, else the data directory. None when morphogen.yaml names another database."""
    import subprocess
    named = "database:" in cfg_text and re.search(r"^\s*url:\s*\S", cfg_text.split("database:", 1)[1], re.M)
    if named or os.environ.get("MORPHOGEN_DATABASE_URL"):
        return None
    try:
        p = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=ROOT, capture_output=True, text=True)
        if p.returncode == 0 and p.stdout.strip():
            common = Path(p.stdout.strip())
            return (common if common.is_absolute() else ROOT / common).resolve() / "morphogen" / "morphogen.db"
    except OSError:
        pass
    return ROOT / setting(cfg_text, "data_dir", ".morphogen") / "morphogen.db"


def read_log(db, name):
    """A log's records, oldest first, read without writing anything (the server owns the database)."""
    import sqlite3
    if db is None or not db.exists():
        return []
    try:
        con = sqlite3.connect(f"{db.as_uri()}?mode=ro", uri=True)
        try:
            return [json.loads(r[0]) for r in con.execute(f"SELECT raw FROM {name} ORDER BY seq")]
        finally:
            con.close()
    except sqlite3.Error:
        return []


def evidence_summary(records):
    prev, last_verdict = "0" * 64, None
    for n, rec in enumerate(records, start=1):
        body = {k: v for k, v in rec.items() if k != "hash"}
        if rec.get("prev") != prev or hashlib.sha256(canonical(body).encode()).hexdigest() != rec.get("hash"):
            return n, f"BROKEN at record {n}", last_verdict
        prev = rec["hash"]
        if rec.get("kind") == "verdict":
            last_verdict = rec
    return len(records), "intact", last_verdict


def session(cfg_text):
    if not cfg_text:
        print("Morphogen is installed but not set up in this project. To start: /morphogen:onboard")
        return
    db = database_file(cfg_text)
    n, chain, verdict = evidence_summary(read_log(db, "evidence"))
    targets = re.findall(r"^\s*-\s*(\S+)", cfg_text.split("targets:", 1)[1], re.M) if "targets:" in cfg_text else []
    lines = [
        f"Morphogen: autonomy {setting(cfg_text, 'autonomy', '2')}, trunk {setting(cfg_text, 'trunk', 'main')}, "
        f"targets {', '.join(targets) or 'none'}.",
        f"Evidence: {n} records, chain {chain}." if db else "Evidence: in the configured database (call doctor).",
    ]
    if verdict:
        lines.append(f"Last verdict: {verdict.get('claim')} ({verdict.get('verdict')}).")
    last = read_log(db, "journal")[-1:]
    if last:
        lines.append(f"Last journal entry: {last[0].get('title')}.")
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
