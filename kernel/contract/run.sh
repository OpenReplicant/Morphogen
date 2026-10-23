#!/usr/bin/env sh
# Conformance check for every provider (or the ones named). See run.py.
# Usage: PGHOST=... PGUSER=<superuser> sh kernel/contract/run.sh [provider ...]
# Needs Python with kernel/contract/requirements.txt; set KK_PYTHON to use a virtualenv's python.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
exec "${KK_PYTHON:-python3}" "$here/run.py" "$@"
