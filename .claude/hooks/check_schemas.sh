#!/usr/bin/env bash
# After any edit: every JSON Schema in schemas/ must be a valid schema, and the
# example blueprint must validate. Non-zero exit (2) feeds the error back to Claude.
set -euo pipefail
input="$(cat)"
case "$input" in
  *schemas/*|*examples/*|*contracts/*) ;;
  *) exit 0 ;;
esac
uv run python - <<'PY' || exit 2
import json, pathlib, sys
from jsonschema import Draft202012Validator
root = pathlib.Path(".")
for p in root.glob("schemas/**/*.json"):
    Draft202012Validator.check_schema(json.loads(p.read_text()))
env = Draft202012Validator(json.loads((root/"schemas/events/cloudevents-extensions.json").read_text()))
bp = json.loads((root/"examples/self-blueprint.json").read_text())
errs = [e.message for e in env.iter_errors(bp)]
data = Draft202012Validator(json.loads((root/"schemas/events/blueprint-submitted.schema.json").read_text()))
errs += [e.message for e in data.iter_errors(bp["data"])]
if errs:
    print("schema check failed:", *errs, sep="\n", file=sys.stderr); sys.exit(1)
PY
