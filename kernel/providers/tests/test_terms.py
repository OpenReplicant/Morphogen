"""The dependency lines (kk.terms, R5-O18 (7)): every kernel provider declares what it emits and consumes, every term
it names is one a vocabulary pack (or the record's bootstrap) defines, and the kernel's providers are closed among
themselves. The checks are shown to fail: an unknown term, an unmet need, a manifest that declares nothing.

  python3 kernel/providers/tests/test_terms.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KERNEL = HERE.parents[1]
sys.path.insert(0, str(KERNEL / "src"))
from kk import terms  # noqa: E402


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


known = terms.pack_terms(KERNEL / "packs")
mine = terms.manifests(KERNEL / "providers")
check(mine and not terms.undeclared(mine), f"every kernel provider declares emits and consumes: {terms.undeclared(mine)}")
check(not terms.unknown(mine, known), f"every term they name is defined by a pack or the bootstrap: {terms.unknown(mine, known)}")
check(not terms.unmet(mine), f"the kernel's providers are closed among themselves: {terms.unmet(mine)}")
check(terms.expand("kkt:connectsTo") == "https://w3id.org/knowledge-kernel/tosca#connectsTo"
      and terms.expand("http://example.org/x") == "http://example.org/x", "CURIEs expand, IRIs stay")
try:
    terms.expand("nope:thing")
    check(False, "an unknown prefix is refused")
except ValueError:
    check(True, "an unknown prefix is refused")

a = {"emits": ["kkt:NodeTemplate"], "consumes": []}
b = {"emits": [], "consumes": ["kkt:NodeTemplate", "sosa:observedProperty", {"term": "bbo:maxValue", "optional": True}]}
check(terms.unmet({"a": a, "b": b}) == [("b", terms.expand("sosa:observedProperty"))],
      "a need no provider of the selection emits is unmet; an optional one is not")
check(terms.unmet({"a": a, "b": b, "c": {"emits": ["sosa:observedProperty"], "consumes": []}}) == [],
      "adding a provider that emits it closes the selection")
check(terms.unknown({"x": {"emits": ["kkt:noSuchTerm"], "consumes": []}}, known) == [("x", terms.expand("kkt:noSuchTerm"))],
      "a term no pack defines is unknown")
check(terms.unknown({"x": {"emits": ["rdfs:label", "dcterms:source"], "consumes": []}}, known) == [],
      "W3C core terms and the bootstrap's properties are known")
check(terms.unknown({"x": {"emits": ["rdfs:labell", "pplan:Plann", "pplan:Plan"], "consumes": []}}, known)
      == [("x", terms.expand("pplan:Plann")), ("x", terms.expand("rdfs:labell"))], "a misspelt core or P-Plan term is unknown")
check(terms.unmet({"p": {"emits": ["bbo:maxValue"], "consumes": ["bbo:maxValue"]}}) == [("p", terms.expand("bbo:maxValue"))],
      "a provider's own emits do not meet its own needs")
try:
    terms.declared({"id": "urn:kk:provider:x", "emits": ["nope:thing"], "consumes": []})
    check(False, "a bad term names its provider")
except ValueError as e:
    check("urn:kk:provider:x" in str(e), f"a bad term names its provider: {e}")
check(terms.undeclared({"x": {"emits": []}}) == ["x"], "a manifest without consumes has not declared its lines")
print("kk.terms tests passed")
