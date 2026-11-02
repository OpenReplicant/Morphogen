#!/usr/bin/env bash
# Builds the workspace a case runs in. The runner calls it with the workspace as cwd.
#   bare     an empty git repository (for onboarding)
#   mapped   Morphogen set up, the slow-script sample committed on main
#   stalled  as mapped, plus four failed hill-climb verdicts in the evidence log
set -euo pipefail
MODE="${1:-bare}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN="$(cd "$HERE/../.." && pwd)"

git init -q -b main .
git config user.email eval@example.com
git config user.name eval
printf '# Scratch project\n' > README.md

if [ "$MODE" != "bare" ]; then
  cp "$PLUGIN/samples/morphogen.example.yaml" morphogen.yaml
  sed -i.bak -e 's/^sandbox: auto/sandbox: none/' -e 's#^targets: \[\]#targets: [targets/slow-script]#' morphogen.yaml
  rm -f morphogen.yaml.bak
  cp "$PLUGIN/samples/catalogs.yaml" catalogs.yaml
  cp "$PLUGIN/samples/intent.example.md" intent.md
  mkdir -p .morphogen/lists targets
  cp "$PLUGIN"/samples/lists/*.jsonl .morphogen/lists/
  cp -R "$PLUGIN/samples/targets/slow-script" targets/slow-script
  printf '.morphogen/traces.jsonl\n' > .gitignore
fi

git add -A
git commit -q -m "start"

if [ "$MODE" = "stalled" ]; then
  uv run --quiet --project "$PLUGIN/server" python - <<'PY'
import subprocess
from pathlib import Path
from morphogen import project
from morphogen.config import load_config

root = Path.cwd()
cfg = load_config(root)
_, evidence = project.stores(root, cfg)
sha = subprocess.run(["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
for i in range(4):
    evidence.append({
        "claim": f"slow-script: trial {i} is not better than {sha[:12]}", "kind": "verdict", "verdict": "fail",
        "subject": {"system": "slow-script", "path": "targets/slow-script"},
        "outcome": {"metrics": {"wall_seconds": {"primary": True, "gain": 0.02, "ok": False}}},
        "refs": {"base": sha, "candidate": sha},
        "labels": {"strategy": "hill-climb", "family": f"micro-optimisation-{i}"},
        "trust": "measured", "by": "judge",
    })
PY
fi
