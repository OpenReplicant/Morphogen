#!/usr/bin/env sh
# Conformance check: runs a provider's suite and confirms every case in invariants.yaml passed.
# Usage: PGHOST=... PGUSER=<superuser> sh kernel/contract/run.sh [provider]   (default: record-postgres)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
provider=${1:-record-postgres}
log=$(mktemp)
sh "$here/../providers/$provider/tests/run.sh" >"$log" 2>&1 || { cat "$log"; echo "FAIL: provider suite errored"; exit 1; }
python3 - "$here/invariants.yaml" "$log" <<'PY'
import re, sys
spec, log = sys.argv[1], open(sys.argv[2]).read()
try:
    import yaml
    data = yaml.safe_load(open(spec))
    cases = [c for inv in data["invariants"].values() for c in inv["cases"]] + data["pipeline"]["cases"]
except ImportError:  # no PyYAML: read case lines directly
    cases = [l.strip()[2:].strip('"') for l in open(spec) if l.strip().startswith("- ") and "id:" not in l]
passed = set(re.findall(r"ok: (.*)", log))
missing = [c for c in cases if c not in passed]
for c in missing: print("MISSING:", c)
print(f"{len(cases) - len(missing)}/{len(cases)} contract cases passed")
sys.exit(1 if missing else 0)
PY
