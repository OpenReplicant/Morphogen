"""The gap-finder slot's own runner (set.yaml `runner:`): runs every case against one provider's
`<package>.gaps.gaps(claims)`, the package being the one its service runs (provider.yaml `service: python3 -m
<package>`). Prints "ok: <case id>" per passing case. As with the analyser's (R5-21), the provider's code runs in a
child process that gets every case's claims and answers with its gaps as JSON; this process never imports it.
A case with a `then:` stage is checked twice: on its input, and with the stage's services merged in.

  python3 runner.py <provider directory>
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

SET = Path(__file__).resolve().parent
KKT = "https://w3id.org/knowledge-kernel/tosca#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
MAX = "https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue"
PROP = "http://www.w3.org/ns/sosa/observedProperty"
PART = "http://purl.org/dc/terms/isPartOf"
LATENCY = "urn:kk:property:latency-seconds-mean"


def node(name: str) -> str:
    system, service = name.split("/")
    return f"urn:kk:node:{system}:{service}"


def claims(services: dict) -> list[dict]:
    out = []

    def c(s, p, o=None, value=None, q=None):
        out.append({"id": f"c{len(out) + 1}", "subject": s, "predicate": p, "object_entity": o,
                    "object_value": {"@value": value} if value is not None else None, "qualifiers": q or {}})
    for name, d in services.items():
        d = d or {}
        n = node(name)
        c(n, RDF_TYPE, KKT + "NodeTemplate")
        c(n, LABEL, value=name.split("/")[1])
        c(n, KKT + "memberOf", f"urn:kk:system:{name.split('/')[0]}")
        if d.get("image"):          # true: an image pinned by digest; a string: that image as written
            img = d["image"] if isinstance(d["image"], str) else f"example/{name.split('/')[1]}:1@sha256:{'a' * 64}"
            c(n, KKT + "propertyValue", value=img, q={KKT + "propertyName": "image"})
        for k, v in (d.get("settings") or {}).items():
            c(n, KKT + "propertyValue", value=str(v), q={KKT + "propertyName": k})
        for peer in d.get("connects") or []:
            c(n, KKT + "connectsTo", node(peer))
        if d.get("limit"):
            c(n, MAX, value=0.5, q={PROP: LATENCY})
        if d.get("prediction"):
            c(n, MAX, value=0.5, q={PROP: LATENCY, PART: "urn:kk:plan:x"})
    return out


def merged(services: dict, then: dict) -> dict:
    out = {k: dict(v or {}) for k, v in services.items()}
    for k, v in then.items():
        out.setdefault(k, {}).update(v or {})
    return out


CHILD = """
import importlib, json, os, sys
out = os.fdopen(os.dup(1), "w")
os.dup2(2, 1)                                            # the provider's own prints go to stderr
sys.path.insert(0, sys.argv[1])
gaps = importlib.import_module(sys.argv[2] + ".gaps").gaps
answers = []
for stage in json.load(sys.stdin):
    try:
        answers.append({"found": [{"kind": g["kind"], "target": g["target"], "premises": [str(x) for x in g["premises"]]}
                                  for g in gaps(stage)]})
    except Exception as e:
        answers.append({"error": f"{type(e).__name__}: {e}"})
out.write(json.dumps(answers))
"""


def answer(provider: Path, package: str, stages: list[list]) -> list[dict]:
    out = subprocess.run([sys.executable, "-c", CHILD, str(provider), package], input=json.dumps(stages),
                         capture_output=True, text=True, timeout=300)
    try:
        got = json.loads(out.stdout)
        assert isinstance(got, list) and len(got) == len(stages)
        return got
    except (ValueError, AssertionError):
        return [{"error": f"no answer (exit {out.returncode}): {out.stderr.strip()[-300:]}"}] * len(stages)


def judge(found: list[dict], state: list[dict]) -> tuple[list, str | None]:
    """The gaps as {kind, target}, or why one is wrong. A gap derives from claims about its own target: the
    service's, the connections to an unknown peer, or the system's services'."""
    by_id = {c["id"]: c for c in state}
    member = {c["subject"]: c["object_entity"] for c in state if c["predicate"] == KKT + "memberOf"}
    rows = []
    for g in found:
        t, kind = g["target"], g["kind"].rsplit(":", 1)[-1]
        prem = [by_id.get(p) for p in g["premises"]]
        if not prem or None in prem:
            return [], f"a gap on {t} does not derive from claims in its input: {g['premises']}"
        if kind == "unknown-peer":
            ok = all(c["predicate"] == KKT + "connectsTo" and c["object_entity"] == t for c in prem)
        elif t.startswith("urn:kk:system:"):
            ok = all(member.get(c["subject"]) == t for c in prem)
        else:
            ok = all(c["subject"] == t for c in prem)
        if not ok:
            return [], f"a gap on {t} derives from claims about something else: {g['premises']}"
        target = t.removeprefix("urn:kk:system:") if t.startswith("urn:kk:system:") else t.removeprefix("urn:kk:node:").replace(":", "/", 1)
        rows.append({"kind": g["kind"].rsplit(":", 1)[-1], "target": target})
    return sorted(rows, key=lambda r: (r["target"], r["kind"])), None


def main() -> int:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    provider = Path(sys.argv[1]).resolve()
    m = re.fullmatch(r"python3 -m ([a-z_][a-z0-9_]*)", str((yaml.safe_load((provider / "provider.yaml").read_text()) or {}).get("service", "")))
    if not m:
        print("FAIL: the provider's service must be python3 -m <package>")
        return 1
    try:
        import ctypes
        ctypes.CDLL(None).prctl(4, 0, 0, 0, 0)          # PR_SET_DUMPABLE 0
    except (OSError, AttributeError):
        pass
    paths = sorted((SET / "cases").glob("*.yaml"))
    if not paths:
        print(f"FAIL: no cases in {SET}")
        return 1
    cases = [yaml.safe_load(p.read_text()) for p in paths]
    plan = []
    for case in cases:
        stages = [(case["input"]["services"], case["expect"]["gaps"])]
        if case.get("then"):
            stages.append((merged(case["input"]["services"], case["then"]["services"]), case["then"]["expect"]["gaps"]))
        plan.append((case, [(claims(s), e) for s, e in stages]))
    answers = iter(answer(provider, m.group(1), [st for _, stages in plan for st, _ in stages]))
    failed = 0
    for case, stages in plan:
        want, got, error = [], [], None
        for state, expect in stages:
            a = next(answers)
            want.append(sorted(expect, key=lambda r: (r["target"], r["kind"])))
            if "error" in a:
                error = error or a["error"]
                continue
            rows, bad = judge(a["found"], state)
            error = error or bad
            got.append(rows)
        if error:
            failed += 1
            print(f"FAIL: {case['id']}: {error}")
        elif got == want:
            print(f"ok: {case['id']}")
        else:
            failed += 1
            print(f"FAIL: {case['id']}: expected {want}, got {got}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
