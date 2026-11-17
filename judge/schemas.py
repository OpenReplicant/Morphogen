"""Load and check the versioned JSON Schemas in schemas/."""

import hashlib
import json
from functools import cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

SCHEMAS = Path(__file__).resolve().parent.parent / "schemas"
KINDS = {"card": "card.v1.json", "policy": "policy.v1.json", "verdict": "verdict.v1.json"}


class Invalid(ValueError):
    pass


@cache
def _validator(kind):
    docs = {name: json.loads((SCHEMAS / name).read_text()) for name in KINDS.values()}
    registry = Registry().with_resources(
        (url, Resource.from_contents(doc)) for name, doc in docs.items()
        for url in (doc["$id"], name))
    schema = docs[KINDS[kind]]
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, registry=registry, format_checker=FormatChecker())


def errors(kind, doc):
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
            for e in sorted(_validator(kind).iter_errors(doc), key=lambda e: list(map(str, e.absolute_path)))]


def check(kind, doc):
    errs = errors(kind, doc)
    if errs:
        raise Invalid(f"invalid {kind}: " + "; ".join(errs))
    return doc


def canonical(doc):
    """The bytes that are hashed and signed: sorted keys, no spaces, UTF-8, finite numbers only."""
    return json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()


def sha256(doc):
    return hashlib.sha256(canonical(doc)).hexdigest()


def loads_strict(text):
    """Parse JSON refusing duplicate keys and NaN/Infinity, so one document cannot mean two things."""
    def pairs(items):
        out = {}
        for k, v in items:
            if k in out:
                raise Invalid(f"duplicate key {k!r}")
            out[k] = v
        return out

    def bad_constant(c):
        raise Invalid(f"non-finite number {c}")

    return json.loads(text, object_pairs_hook=pairs, parse_constant=bad_constant)
