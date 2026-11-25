"""Check what an engagement left: the done-when of the demo, as checks a script can make.

    python3 demos/fernhill/check.py PROJECT PLUGIN_DIR

PROJECT is the engagement's git repository; PLUGIN_DIR is Morphogen's plugin, whose CLI does the structure and
status checks. Standard library only. Prints one line per check and exits 1 if any fails. It checks the form of
the result, not its judgement: whether the opportunities are the right ones is for a person reading report.md.
"""

import json
import re
import subprocess
import sys
from pathlib import Path

proj, plugin = Path(sys.argv[1]).resolve(), sys.argv[2]
results = []


def check(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f": {detail}" if detail else ""))


def git(*args):
    return subprocess.run(["git", *args], cwd=proj, capture_output=True, text=True).stdout


def morphogen(*args):
    r = subprocess.run(["uv", "run", "--quiet", "--project", plugin, "morphogen", *args], cwd=proj,
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return {"error": (r.stdout + r.stderr).strip()[-300:]}


tracked = set(git("ls-files").split())
check("report.md committed on main", "report.md" in git("ls-tree", "--name-only", "main").split())
check("the client's material is not committed", not any(p.startswith("material/") for p in tracked))
catalog = [proj / p for p in tracked if p.endswith((".yaml", ".yml")) and (p == "catalog-info.yaml" or p.startswith("catalog/"))]
check("a catalog", (proj / "catalog-info.yaml") in catalog, f"{len(catalog)} files")

found = morphogen("structure", "check", "catalog-info.yaml")
errors = [f for f in found.get("findings", []) if f.get("severity") == "error"]
check("structure check: no errors", "error" not in found and not errors,
      found.get("error") or "; ".join(f["message"] for f in errors[:3]))

status = morphogen("status")
judged = [c["cell"] for c in status.get("cells", []) if c.get("verdicts")]
check("a cell with a verdict", bool(judged), ", ".join(judged) or status.get("next", status.get("error", "")))

text = "\n".join(p.read_text() for p in catalog if p.exists())
candidates = len(re.findall(r"lifecycle:\s*candidate", text))
check("at least three options for a role", candidates >= 3, f"{candidates} candidates")

# Evidence lines: `trust | file:Lnn[-mm] | "quote"`. A quote must be on the lines it names; URLs are not fetched.
total, misses = 0, []
for m in re.finditer(r'^\s*(stated|inferred) \| ([^|\s]+?):L(\d+)(?:-(\d+))? \| "(.+)"\s*$', text, re.M):
    _, path, a, b, quote = m.groups()
    total += 1
    src = proj / path
    lines = src.read_text().splitlines() if src.is_file() else []
    span = "\n".join(lines[int(a) - 1:int(b or a)])
    if quote.strip('"') not in span:
        misses.append(f"{path}:L{a}")
check("evidence quotes are where they say", total > 0 and not misses,
      f"{total - len(misses)} of {total}" + (f"; first misses: {', '.join(misses[:3])}" if misses else ""))

report = (proj / "report.md").read_text() if (proj / "report.md").exists() else ""
words = ["target", "measure", "option", "cost", "risk"]
absent = [w for w in words if w not in report.lower()]
check("the report writes opportunities up as projects", not absent, "missing: " + ", ".join(absent) if absent else "")

sys.exit(0 if all(results) else 1)
