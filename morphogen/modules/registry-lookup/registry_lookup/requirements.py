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
`properties`, plus `licence`, `version` and `kind`. A property the entry does not state fails its requirement:
missing is never a match.

  holds(constraint, required, actual) -> (ok, why)
  match(requirements, entry)          -> (every requirement holds, [(requirement, ok, why)])
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


def _order(required, actual):
    """(actual, required) as numbers, else as versions, else None."""
    a, r = _number(actual), _number(required)
    if a is not None and r is not None:
        return a, r
    a, r = _version(actual), _version(required)
    return (a, r) if a is not None and r is not None else None


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
        return (spdx(t) or t).lower()

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
        if pos < len(tokens) and tokens[pos] == "WITH":   # an exception narrows a licence; it never widens it
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
        if not re.search(r"\b(AND|OR|WITH)\b|\(", expr) and spdx(expr):
            return ident(expr) in allowed            # a name a registry wrote ("MIT License"), not an expression
        v = disj()
        return v if pos == len(tokens) else None
    except (ValueError, IndexError):
        return None


def holds(constraint: str, required, actual) -> tuple[bool, str]:
    if actual is None or str(actual).strip() == "":
        return False, "not stated"
    if constraint == "$equal":
        a, r = _number(actual), _number(required)
        ok = a == r if a is not None and r is not None else str(actual).strip().lower() == str(required).strip().lower()
        return ok, f"{actual!r} {'is' if ok else 'is not'} {required!r}"
    if constraint in ("$greater_or_equal", "$less_or_equal"):
        pair = _order(required, actual)
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
        allowed = {(spdx(x) or x).lower() for x in _list(required)}
        ok = _licence_ok(str(actual), allowed)
        if ok is None:
            return False, f"licence {actual!r} cannot be read"
        return ok, f"licence {actual!r} {'can' if ok else 'cannot'} be met with {sorted(allowed)}"
    return False, f"unknown constraint {constraint!r}"


def properties(entry: dict) -> dict:
    out = {str(k): v for k, v in (entry.get("properties") or {}).items()}
    for k in ("licence", "version", "kind"):
        if entry.get(k) is not None:
            out.setdefault(k, entry[k])
    return out


def match(requirements: list[dict], entry: dict) -> tuple[bool, list[tuple[dict, bool, str]]]:
    """requirements: [{name, constraint, value}]. Every requirement must hold; none listed is no match."""
    props = properties(entry)
    results = [(r, *holds(r["constraint"], r["value"], props.get(r["name"]))) for r in requirements]
    return bool(results) and all(ok for _, ok, _ in results), results
