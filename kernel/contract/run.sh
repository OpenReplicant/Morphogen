#!/usr/bin/env sh
# Conformance check: the record's API against kernel/contract/api.yaml (api.py), then every provider (or the ones
# named) against its slots' contracts (run.py).
# Usage: PGHOST=... PGUSER=<superuser> sh kernel/contract/run.sh [provider ...]
# Needs Python with kernel/contract/requirements.txt; set KK_PYTHON to use a virtualenv's python.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
"${KK_PYTHON:-python3}" "$here/api.py" check
exec "${KK_PYTHON:-python3}" "$here/run.py" "$@"
