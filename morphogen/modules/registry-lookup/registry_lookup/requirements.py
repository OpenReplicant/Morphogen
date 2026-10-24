"""Requirement matching (T20, R5-O7 a3): an entry's properties against a need's requirements, deterministically.
No database, no model.

A requirement is (property name, constraint, required value); recorded, it is a claim
`<need> kkt:propertyValue "<value>"` qualified by `kkt:propertyName` and `kkt:constraint`. Constraints:

  $equal             the same value (numbers compared as numbers, else text, ignoring case)
  $greater_or_equal  at least the value (two plain decimals as numbers, so 1.10 < 1.9; else as versions, so
                     1.10.0 > 1.9.2)
  $less_or_equal     at most the value (the same)
  $valid_values      one of the values (a JSON list)
  $admits            the entry's version specifier (PEP 440, e.g. requires_python ">=3.9") allows the version
  $licence           the entry's licence (an SPDX expression, or a name catalogs.spdx knows) can be met using
                     only the licences listed (a JSON list): OR needs one allowed side, AND needs both

The first four are TOSCA 2.0's validation functions of the same names. An entry's properties are its
`properties`, plus `licence`, `version` and `kind`; a property may have several values (a requirement holds when one
meets it). A property the entry does not state fails its requirement: missing is never a match. In `$licence`, ids in
an expression are compared exactly (MIT-0 is not MIT); only a registry's name with spaces ("BSD License") is read
through catalogs.spdx. A property named `version` (or `*_version`) compares as versions (3.12 > 3.9).

  holds(constraint, required, actual, name) -> (ok, why)
  match(requirements, entry)                -> (every requirement holds, [(requirement, ok, why, claim)])
"""
from __future__ import annotations

import json
import re

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version

from .catalogs import spdx

CONSTRAINTS = ("$equal", "$greater_or_equal", "$less_or_equal", "$valid_values", "$admits", "$licence")


def _number(x):
    try:
        return float(str(x).strip())
    except ValueError:
        return None


def _version(x):
    try:
        return Version(str(x).strip())
    except InvalidVersion:
        return None


def _order(required, actual, versions: bool = False):
    """(actual, required) as numbers, else as versions, else None; a version property always as versions."""
    a, r = _number(actual), _number(required)
    if a is not None and r is not None and not versions:
        return a, r
    a, r = _version(actual), _version(required)
    return (a, r) if a is not None and r is not None else None


def is_version(name) -> bool:
    return bool(name) and (name == "version" or str(name).endswith("_version"))


def _list(required) -> list[str]:
    try:
        v = json.loads(required) if isinstance(required, str) else required
    except ValueError:
        v = [required]
    return [str(x) for x in (v if isinstance(v, list) else [v])]


def _licence_ok(expr: str, allowed: set[str]) -> bool | None:
    """Whether an SPDX expression can be met with the allowed ids; None when it cannot be read."""
    tokens = re.findall(r"\(|\)|[A-Za-z0-9.+-]+", expr)
    pos = 0

    def ident(t):
        return t.lower()                                  # an SPDX id, exactly: MIT-0 is not MIT, Apache-1.1 not Apache-2.0

    def term():
        nonlocal pos
        if pos >= len(tokens):
            raise ValueError
        t = tokens[pos]
        pos += 1
        if t == "(":
            v = disj()
            if pos >= len(tokens) or tokens[pos] != ")":
                raise ValueError
            pos += 1
        elif t in (")", "AND", "OR", "WITH"):
            raise ValueError
        else:
            v = ident(t) in allowed
        if pos < len(tokens) and tokens[pos] == "WITH":   # an exception only adds permissions: met by the licence alone
            pos += 2
        return v

    def conj():
        nonlocal pos
        v = term()
        while pos < len(tokens) and tokens[pos] == "AND":
            pos += 1
            v = term() and v
        return v

    def disj():
        nonlocal pos
        v = conj()
        while pos < len(tokens) and tokens[pos] == "OR":
            pos += 1
            v = conj() or v
        return v
    try:
        if not tokens:
            return None
        if " " in expr.strip() and not re.search(r"\b(AND|OR|WITH)\b|\(", expr):
            name = spdx(expr)                        # a name a registry wrote ("MIT License"), not an expression
            return None if name is None else name.lower() in allowed
        v = disj()
        return v if pos == len(tokens) else None
    except (ValueError, IndexError):
        return None


def holds(constraint: str, required, actual, name: str | None = None) -> tuple[bool, str]:
    if actual is None or str(actual).strip() == "":
        return False, "not stated"
    if constraint == "$equal":
        pair = _order(required, actual, is_version(name)) if is_version(name) else None
        a, r = pair if pair else (_number(actual), _number(required))
        ok = a == r if a is not None and r is not None else str(actual).strip().lower() == str(required).strip().lower()
        return ok, f"{actual!r} {'is' if ok else 'is not'} {required!r}"
    if constraint in ("$greater_or_equal", "$less_or_equal"):
        pair = _order(required, actual, is_version(name))
        if pair is None:
            return False, f"{actual!r} and {required!r} cannot be compared"
        a, r = pair
        ok = a >= r if constraint == "$greater_or_equal" else a <= r
        return ok, f"{actual!r} {'>=' if constraint == '$greater_or_equal' else '<='} {required!r}: {'yes' if ok else 'no'}"
    if constraint == "$valid_values":
        values = _list(required)
        ok = str(actual).strip().lower() in {v.strip().lower() for v in values}
        return ok, f"{actual!r} {'is' if ok else 'is not'} one of {values}"
    if constraint == "$admits":
        v = _version(required)
        try:
            spec = SpecifierSet(str(actual))
        except InvalidSpecifier:
            return False, f"{actual!r} is not a version specifier"
        if v is None:
            return False, f"{required!r} is not a version"
        ok = spec.contains(v, prereleases=True)
        return ok, f"{actual!r} {'allows' if ok else 'does not allow'} {required}"
    if constraint == "$licence":
        allowed = {x.strip().lower() for x in _list(required)}
        ok = _licence_ok(str(actual), allowed)
        if ok is None:
            return False, f"licence {actual!r} cannot be read"
        return ok, f"licence {actual!r} {'can' if ok else 'cannot'} be met with {sorted(allowed)}"
    return False, f"unknown constraint {constraint!r}"


def properties(entry: dict) -> dict[str, list[tuple]]:
    """Each property's values, as (value, claim id or None): an entry may state a property more than once (the
    slots a provider fills)."""
    out: dict[str, list[tuple]] = {}
    for k, v in (entry.get("properties") or {}).items():
        vals = v if isinstance(v, list) else [v]
        out[str(k)] = [x if isinstance(x, tuple) else (x, None) for x in vals]
    for k in ("licence", "version", "kind"):
        if entry.get(k) is not None:
            out.setdefault(k, [(entry[k], None)])
    return out


def match(requirements: list[dict], entry: dict) -> tuple[bool, list[tuple[dict, bool, str, object]]]:
    """requirements: [{name, constraint, value}]. Each holds when one of the property's values meets it; the result
    names that value's claim. Every requirement must hold; no requirements is no match."""
    props = properties(entry)
    results = []
    for r in requirements:
        got = (r, False, "not stated", None)
        for v, claim in props.get(r["name"], []):
            ok, why = holds(r["constraint"], r["value"], v, r["name"])
            got = (r, ok, why, claim)
            if ok:
                break
        results.append(got)
    return bool(results) and all(ok for _, ok, _, _ in results), results
