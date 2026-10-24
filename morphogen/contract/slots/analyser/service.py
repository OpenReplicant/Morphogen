"""The analyser slot's service cases (R5-23): the same cases as runner.py, run through the provider's own
reading of the record instead of its rule alone. The sandbox loads every case into one fresh database
(each case's targets suffixed with `-c<n>`, so cases cannot see each other), runs one pass of the
provider (its benchmark entry, as the incumbent's login), and gives the change sets the provider
submitted to `judge`. Slot code, run by the sandbox; it never imports the provider.

  ops(paths)                 -> (add_claim ops loading every case, expected anomalies per case)
  judge(change_sets, ids, expected) -> {"passed", "total", "failed": [case id, ...]}
  outputs(change_sets, name) -> the anomalies submitted, as [kind, target, [premise names]], sorted

The sandbox judges only change sets that were applied and attributed to the incumbent's agent. It also
compares the candidate's `outputs` on the benchmark with the incumbent's on the same inputs (`name` gives
each premise a name that does not depend on the database), so a provider cannot read the record one way
for the cases and another way for the benchmark.

Observations are loaded as `observed` claims, limits as `testimony`, each referencing
`urn:kk:case:<n>/<obs|limit>/<local id>`; `ids` maps claim ids back to (n, obs|limit, local id) (`ref`).
"""
from __future__ import annotations

import importlib.util
from datetime import timedelta
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("analyser_runner", HERE / "runner.py")
runner = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(runner)

SOSA = "http://www.w3.org/ns/sosa/"
DCT_TYPE = "http://purl.org/dc/terms/type"
OA_TARGET = "http://www.w3.org/ns/oa#hasTarget"
XSD = "http://www.w3.org/2001/XMLSchema#decimal"


def ref(uri: str) -> tuple[int, str, str] | None:
    parts = uri.removeprefix("urn:kk:case:").split("/") if uri.startswith("urn:kk:case:") else []
    return (int(parts[0]), parts[1], parts[2]) if len(parts) == 3 and parts[0].isdigit() else None


def suffix(target: str, n: int) -> str:
    return f"{target}-c{n:02d}"


def ops(paths: list[Path]) -> tuple[list[dict], dict[int, dict]]:
    out, expected = [], {}
    for n, path in enumerate(sorted(paths)):
        case = yaml.safe_load(path.read_text())
        expected[n] = {"id": case["id"], "anomalies": sorted(case["expect"]["anomalies"],
                                                            key=lambda r: (r["target"], r["observation"], r["kind"]))}
        for o in case["input"]["observations"]:
            t = runner.T0 + timedelta(minutes=o["window"])
            out.append({"op": "add_claim", "subject": suffix(o["target"], n), "predicate": SOSA + "hasSimpleResult",
                        "object": {"value": {"@value": o["value"], "@type": XSD}},
                        "qualifiers": {runner.PROP: o["property"], **(o.get("extra") or {})},
                        "valid_from": t.isoformat(), "valid_to": (t + timedelta(minutes=1)).isoformat(),
                        "evidence_type": "observed", "references": [{"source_uri": f"urn:kk:case:{n}/obs/{o['id']}"}]})
        for x in case["input"]["limits"]:
            out.append({"op": "add_claim", "subject": suffix(x["target"], n), "predicate": runner.MAX,
                        "object": {"value": {"@value": x["value"], "@type": XSD}}, "qualifiers": {runner.PROP: x["property"]},
                        "evidence_type": "testimony", "references": [{"source_uri": f"urn:kk:case:{n}/limit/{x['id']}"}]})
    return out, expected


def found(change_sets: list[list[dict]]) -> list[dict]:
    """The anomalies in these change sets: {kind, target, premises}. An anomaly is the subject of a
    dcterms:type and an oa:hasTarget op; its premises are the ops' derived_from (the observation first,
    as the rule cases read them)."""
    out = []
    for cs in change_sets:
        by: dict[str, dict] = {}
        for op in cs:
            a = by.setdefault(op.get("subject"), {"premises": op.get("derived_from") or []})
            if op.get("predicate") == DCT_TYPE:
                a["kind"] = (op.get("object") or {}).get("entity")
            elif op.get("predicate") == OA_TARGET:
                a["target"] = (op.get("object") or {}).get("entity")
        out += [a for a in by.values() if a.get("kind") and a.get("target") and a["premises"]]
    return out


def outputs(change_sets: list[list[dict]], name: dict[str, str]) -> list:
    return sorted([a["kind"].rsplit(":", 1)[-1], a["target"], [name.get(str(p), "?") for p in a["premises"]]]
                  for a in found(change_sets))


def judge(change_sets: list[list[dict]], ids: dict[str, tuple[int, str, str]], expected: dict[int, dict]) -> dict:
    """change_sets: the ops of each applied change set the provider submitted."""
    got: dict[int, list[dict]] = {n: [] for n in expected}
    for a in found(change_sets):
        first = ids.get(str(a["premises"][0]))
        if first is None or first[1] != "obs":
            continue
        n, _, obs = first
        kind = a["kind"].rsplit(":", 1)[-1]
        target = a["target"].removesuffix(f"-c{n:02d}")
        row = {"kind": kind, "target": target, "observation": obs}
        if kind == "limit":
            row["limit"] = next((ids[str(p)][2] for p in a["premises"] if ids.get(str(p), (None, None))[:2] == (n, "limit")), None)
        got[n].append(row)
    failed = [expected[n]["id"] for n in expected
              if sorted(got[n], key=lambda r: (r["target"], r["observation"], r["kind"])) != expected[n]["anomalies"]]
    return {"passed": len(expected) - len(failed), "total": len(expected), "failed": failed}
