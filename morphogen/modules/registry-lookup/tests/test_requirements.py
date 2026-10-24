"""Requirement matching (T20): a Python package that must run on Python 3.12 and an M8 stainless bolt of a given
length, matched and mismatched alike; a missing property is never a match. No database, no network.

  python3 tests/test_requirements.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "morphogen" / "src")]
from registry_lookup.requirements import holds, match  # noqa: E402


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


def req(name, constraint, value):
    return {"name": name, "constraint": constraint, "value": value}


# A Python package that runs on 3.12, under a permissive licence.
NEED_PY = [req("requires_python", "$admits", "3.12"), req("licence", "$licence", '["MIT", "BSD-3-Clause", "Apache-2.0"]')]
old = {"id": "a", "licence": "MIT", "properties": {"requires_python": ">=3.9"}}
new = {"id": "b", "licence": "MIT", "properties": {"requires_python": ">=3.13"}}
gpl = {"id": "c", "licence": "GPL-3.0-only", "properties": {"requires_python": ">=3.8"}}
dual = {"id": "d", "licence": "Apache-2.0 OR GPL-2.0-only", "properties": {"requires_python": ">=3.10,<3.14"}}
both = {"id": "e", "licence": "MIT AND GPL-3.0-only", "properties": {"requires_python": ">=3.8"}}
named = {"id": "f", "licence": "BSD License", "properties": {"requires_python": ">=3.8"}}
nopy = {"id": "g", "licence": "MIT"}
check(match(NEED_PY, old)[0], "requires_python >=3.9 admits 3.12, licence MIT allowed: matched")
check(not match(NEED_PY, new)[0], "requires_python >=3.13 does not admit 3.12: not matched")
check(not match(NEED_PY, gpl)[0], "a GPL licence is not on the list: not matched")
check(match(NEED_PY, dual)[0], "Apache-2.0 OR GPL-2.0-only can be met with Apache-2.0 alone: matched")
check(not match(NEED_PY, both)[0], "MIT AND GPL-3.0-only needs both: not matched")
check(match(NEED_PY, named)[0], "a registry's licence name (\"BSD License\") is read as its SPDX id")
ok, results = match(NEED_PY, nopy)
check(not ok and any(r["name"] == "requires_python" and not good and why == "not stated" for r, good, why in results),
      "an entry that does not state requires_python is not matched: missing is never a match")

# An M8 stainless bolt, 25 to 40 mm long.
NEED_BOLT = [req("thread", "$equal", "M8"), req("length_mm", "$greater_or_equal", "25"), req("length_mm", "$less_or_equal", "40"),
             req("material", "$valid_values", '["stainless steel A2-70", "stainless steel A4-80"]')]
bolt = {"id": "m8-bolt-a2-30", "kind": "fastener", "properties": {"thread": "M8", "length_mm": 30, "material": "stainless steel A2-70"}}
long_ = {"id": "m8-bolt-a2-60", "properties": {"thread": "M8", "length_mm": 60, "material": "stainless steel A2-70"}}
zinc = {"id": "m8-bolt-zn-30", "properties": {"thread": "M8", "length_mm": 30, "material": "steel 8.8 zinc plated"}}
m10 = {"id": "m10-bolt-a2-30", "properties": {"thread": "m10", "length_mm": 30, "material": "stainless steel A2-70"}}
nut = {"id": "m8-nut-a2", "properties": {"thread": "M8", "material": "stainless steel A2-70"}}
check(match(NEED_BOLT, bolt)[0], "M8 x 30 A2: every requirement holds")
check(not match(NEED_BOLT, long_)[0], "60 mm is over 40: not matched")
check(not match(NEED_BOLT, zinc)[0], "zinc-plated steel is not one of the materials: not matched")
check(not match(NEED_BOLT, m10)[0], "an M10 thread is not M8: not matched")
check(not match(NEED_BOLT, nut)[0], "a nut states no length: not matched")
check(not match([], bolt)[0], "no requirements: nothing is matched (a need states what it needs)")

# The comparisons on their own.
check(holds("$equal", "8", "8.0")[0] and holds("$equal", "m8", "M8")[0], "equal compares numbers as numbers, text ignoring case")
check(holds("$greater_or_equal", "1.10.0", "1.9.2")[0] is False and holds("$greater_or_equal", "1.9.2", "1.10.0")[0],
      "at least: versions compare as versions (1.10.0 > 1.9.2), not as text")
check(holds("$greater_or_equal", "1.10", "1.9")[0], "two plain decimals compare as numbers (1.9 >= 1.10)")
check(holds("$less_or_equal", "40", "40")[0] and not holds("$less_or_equal", "40", "40.5")[0], "at most includes the bound")
check(not holds("$greater_or_equal", "25", "long")[0], "a value that is neither a number nor a version cannot be compared")
check(not holds("$admits", "3.12", "not a specifier")[0], "a value that is not a specifier admits nothing")
check(not holds("$licence", '["MIT"]', "MIT OR (")[0], "an unreadable licence expression is not met")
check(not holds("$approx", "1", "1")[0], "an unknown constraint never holds")
