"""Only sh:Violation refuses a change set (R5-O18 (5)): a shape at sh:Warning is a gap to ask about, so a pack that
carries both kinds can reach the validator without its questions refusing intake. No database needed.

  python3 tests/test_severity.py
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parents[2] / "src")]
from rdflib import Graph  # noqa: E402

from validator import core  # noqa: E402

CASES = HERE.parents[2] / "contract" / "slots" / "validator"
cs = json.loads((CASES / "fixtures" / "deterministic-with-source.json").read_text())


def shape(severity: str) -> Graph:
    """A rule every claim of the fixture breaks: a claim's statement needs an rdfs:comment."""
    return Graph().parse(data=f"""@prefix sh: <http://www.w3.org/ns/shacl#> .
        <urn:test:NeedsComment> a sh:PropertyShape ;
            sh:targetClass <http://www.w3.org/1999/02/22-rdf-syntax-ns#Statement> ;
            sh:path <http://www.w3.org/2000/01/rdf-schema#comment> ; sh:minCount 1 ; sh:severity sh:{severity} .""",
                         format="turtle")


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


base = core.SHAPES
check(core.validate(cs, [])[0], "the fixture is valid with the kernel's shapes")
try:
    core.SHAPES = base + shape("Violation")
    ok, report = core.validate(cs, [])
    check(not ok and report["shape_violations"], "a shape at sh:Violation the claims break refuses the change set")
    core.SHAPES = base + shape("Warning")
    ok, report = core.validate(cs, [])
    check(ok and not report["shape_violations"], f"a shape at sh:Warning the claims break does not: {report}")
finally:
    core.SHAPES = base
print("validator severity tests passed")
