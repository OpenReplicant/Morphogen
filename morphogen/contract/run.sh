#!/usr/bin/env sh
# Conformance check for Morphogen's modules against the slots they fill (kernel slots and Morphogen's).
# Usage: sh morphogen/contract/run.sh [module ...]; mutants: sh morphogen/contract/run.sh --mutants [-k filter]
# Uses the kernel's runner (kernel/contract/run.py); set KK_PYTHON to use a virtualenv's python.
set -eu
here=$(cd "$(dirname "$0")" && pwd)
root=$(cd "$here/../.." && pwd)
py="${KK_PYTHON:-python3}"
args="--blueprint $root/kernel/blueprint/slots.yaml --blueprint $root/morphogen/distribution.yaml --providers $root/morphogen/modules"
if [ "${1:-}" = "--mutants" ]; then
  shift
  exec "$py" "$root/kernel/contract/mutants.py" $args "$@"
fi
exec "$py" "$root/kernel/contract/run.py" $args "$@"
