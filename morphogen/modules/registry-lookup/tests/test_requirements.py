"""Requirement matching (T20): a Python package that must run on Python 3.12 and an M8 stainless bolt of a given
length, matched and mismatched alike; a missing property is never a match. No database, no network.

  python3 tests/test_requirements.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "morphogen" / "src"), str(ROOT / "kernel" / "src")]
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
check(not ok and any(r["name"] == "requires_python" and not good and why == "not stated" for r, good, why, _ in results),
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
check(not holds("$greater_or_equal", "1.10", "1.9", "version")[0] and holds("$greater_or_equal", "3.9", "3.12", "version")[0]
      and not holds("$equal", "1.1", "1.10", "version")[0], "a property named version compares as versions (3.12 >= 3.9, 1.10 is not 1.1)")
check(holds("$less_or_equal", "40", "40")[0] and not holds("$less_or_equal", "40", "40.5")[0], "at most includes the bound")
check(not holds("$greater_or_equal", "25", "long")[0], "a value that is neither a number nor a version cannot be compared")
check(not holds("$admits", "3.12", "not a specifier")[0], "a value that is not a specifier admits nothing")
check(not holds("$licence", '["MIT"]', "MIT OR (")[0], "an unreadable licence expression is not met")
check(not holds("$approx", "1", "1")[0], "an unknown constraint never holds")
check(not holds("$valid_values", '[""]', "")[0] and not holds("$equal", "", " ")[0], "an empty value is not stated")

# Licence ids in an expression are exact; a registry's name with spaces is read as its SPDX id.
ALLOWED = '["Apache-2.0", "MIT", "MPL-2.0"]'
for lic in ("Apache-1.1", "MPL-1.1", "MIT-0", "LicenseRef-Proprietary-MIT-like", "GPL-3.0-or-later"):
    check(not holds("$licence", ALLOWED, lic)[0], f"{lic} is not on the list (no mapping across versions or variants)")
check(not holds("$licence", '["MIT-0"]', "MIT")[0] and not holds("$licence", '["GPL-3.0-only"]', "GPL-3.0-or-later")[0],
      "an allowed id admits only itself")
check(holds("$licence", ALLOWED, "MIT License")[0] and holds("$licence", ALLOWED, "Apache-2.0 WITH LLVM-exception")[0],
      "a registry's name is read as its id; an exception only adds permissions")

# Several values: a requirement holds when one of them meets it, and names that value's claim.
prov = {"properties": {"slot": [("analyser", "s1"), ("observer", "s2")]}}
ok, res = match([req("slot", "$equal", "observer")], prov)
check(ok and res[0][3] == "s2", "a provider filling two slots meets a need for either; the claim of the one that met it is cited")

# What catalog lookup recorded, grouped per (entry, catalog): one catalog's values never stand for another's.
from registry_lookup.__main__ import DCT, KKT, OWL_VERSION, group  # noqa: E402
P, A, B = "urn:kk:provider:x", "urn:kk:catalog:a", "urn:kk:catalog:b"
V = lambda x: {"@value": x}  # noqa: E731
rows = [("1", P, DCT + "isPartOf", A, None, {}), ("2", P, DCT + "isPartOf", B, None, {}),
        ("3", P, DCT + "license", None, V("MIT"), {DCT + "isPartOf": A}),
        ("4", P, DCT + "license", None, V("GPL-3.0-only"), {DCT + "isPartOf": B}),
        ("5", P, KKT + "propertyValue", None, V("analyser"), {KKT + "propertyName": "slot", DCT + "isPartOf": A}),
        ("6", P, KKT + "propertyValue", None, V("observer"), {KKT + "propertyName": "slot", DCT + "isPartOf": A}),
        ("7", P, KKT + "propertyValue", None, V("fails: licence (enforced)"), {KKT + "propertyName": "rule:licences", DCT + "isPartOf": B}),
        ("8", P, OWL_VERSION, None, V("1.0"), {}),
        ("9", "urn:kk:provider:y", KKT + "propertyValue", None, V("z"), {KKT + "propertyName": "slot", DCT + "isPartOf": A})]
g = group(rows)
check(g[(P, A)]["properties"]["licence"] == [("MIT", "3")] and g[(P, B)]["properties"]["licence"] == [("GPL-3.0-only", "4")],
      "two catalogs disagreeing about one provider's licence: each keeps its own, with its own claim")
check(g[(P, A)]["properties"]["slot"] == [("analyser", "5"), ("observer", "6")], "every value of a property is kept")
check(g[(P, B)]["refused"] and g[(P, B)]["rules"] == ["7"] and not g[(P, A)]["refused"], "an enforced rule refuses the entry in its own catalog only")
check("version" not in g[(P, A)]["properties"], "a value no catalog qualified is not used")
check(("urn:kk:provider:y", A) not in g and g[(P, A)]["member"] == "1", "only an entry recorded as in the catalog is matched")
