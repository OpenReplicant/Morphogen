"""map-gaps and the kernel's shape-driven gap finder agree (R5-47): on random system maps they find the same kinds
and targets, and rest on the same claims where map-gaps rests on the claims that put a service on the map. map-gaps
stays Morphogen's alternative provider of the kernel's gap-finder slot until it is retired.

  python3 tests/test_parity.py
"""
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "kernel" / "providers" / "gaps-shacl"), str(ROOT / "kernel" / "contract" / "slots" / "gap-finder"),
                str(ROOT / "kernel" / "src")]
from gaps_shacl.gaps import gaps, shapes  # noqa: E402
from map_gaps.gaps import gaps as python_gaps  # noqa: E402
from runner import claims  # noqa: E402


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


RULES = shapes()
rng = random.Random(5)
for n in range(100):
    systems = [f"s{i}" for i in range(rng.randint(1, 3))]
    names = [f"{s}/v{j}" for s in systems for j in range(rng.randint(1, 4))]
    services = {}
    for name in names:
        d = {"image": rng.choice([None, True, "example/x:1", "example/x:1@sha256:" + "b" * rng.choice([12, 64])]),
             "connects": rng.sample(names + ["s0/ghost", "s9/ext"], rng.randint(0, 2)),
             "limit": rng.random() < 0.3, "prediction": rng.random() < 0.3}
        services[name] = {k: v for k, v in d.items() if v}
    state = claims(services)
    py, sh = python_gaps(state), gaps(state, RULES)
    want, have = {(g["kind"], g["target"]) for g in py}, {(g["kind"], g["target"]) for g in sh}
    if want != have:
        check(False, f"map {n}: map-gaps and the shapes differ: only map-gaps {want - have}, only shapes {have - want}; {services}")
    same = {g["iri"]: g["premises"] for g in py if not g["kind"].endswith("unpinned-image") and g["target"].startswith("urn:kk:node:")}
    for g in sh:
        if g["iri"] in same and g["premises"] != same[g["iri"]]:
            check(False, f"map {n}: {g['kind']} on {g['target']} rests on {g['premises']}, map-gaps on {same[g['iri']]}")
print("ok: 100 random maps: the shapes find map-gaps' kinds and targets, and the same premises where map-gaps rests on "
      "the claims that put a service on the map")
print("map-gaps parity tests passed")
