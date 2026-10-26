"""Morphogen's default selection is closed (R5-47): every term a default provider needs (provider.yaml `consumes`) is
emitted by another default provider, and every term any Morphogen module names is one a pack defines. The check is
shown to fail on the real selection where a term has one source: without the planner nothing emits the predictions the
outcome verifier checks, and without the pack loader nothing emits the subproperty links the planner follows. Where a
term has several uses it cannot fail: an observation and a prediction both carry sosa:observedProperty, a gap and an
anomaly are both oa:Annotation, so removing the observers or the gap finder leaves the selection "closed" (R5-47).

  python3 morphogen/tests/test_closure.py
"""
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "kernel" / "src"))
from kk import terms  # noqa: E402


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def defaults() -> set[str]:
    """The providers Morphogen runs by default: the kernel slots it uses and its own slots, as their files say."""
    dist = yaml.safe_load((ROOT / "morphogen" / "distribution.yaml").read_text())
    kernel = {s["id"]: s for s in yaml.safe_load((ROOT / "kernel" / "blueprint" / "slots.yaml").read_text())["slots"]}
    names = {kernel[s]["default"] for s in dist["uses_kernel_slots"]} | {dist["lane_policy"]["provider"]}
    names |= {n.strip() for s in dist["slots"] for n in str(s["default"]).split("+")}
    return names - {"none"}


every = terms.manifests(ROOT / "kernel" / "providers", ROOT / "morphogen" / "modules")
known = terms.pack_terms(ROOT / "kernel" / "packs")
check(not terms.undeclared(every), f"every provider declares emits and consumes: {terms.undeclared(every)}")
check(not terms.unknown(every, known), f"every term a provider names is defined by a pack: {terms.unknown(every, known)}")
chosen = defaults()
check(chosen <= set(every), f"every default named in the distribution exists: {sorted(chosen - set(every))}")
selection = {n: every[n] for n in chosen}
check(not terms.unmet(selection), f"Morphogen's default selection is closed: {terms.unmet(selection)}")
BBO = "https://www.irit.fr/recherches/MELODI/ontologies/BBO#"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
without = {n: m for n, m in selection.items() if n != "pack-loader"}
check(("planner", RDFS + "subPropertyOf") in terms.unmet(without), "without the pack loader, the planner's subproperty links are unmet")
without = {n: m for n, m in selection.items() if n != "planner"}
check(("prediction-verifier", BBO + "maxValue") in terms.unmet(without),
      "without the planner, the predictions the outcome verifier checks are unmet")
print("closure tests passed")
