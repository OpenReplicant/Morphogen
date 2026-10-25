"""Plan steps as the record holds them (R5-07): what the intent actuator carries out and what a runtime may run
(T26). Pure; no database.

A plan step is a sosa:Actuation that is p-plan:isStepOfPlan a plan, with dcterms:type an action from the fixed list
(intent/policies/actions.yaml), sosa:hasFeatureOfInterest its target and the new value as sosa:hasSimpleResult. The
result may be qualified by spdx:checksumValue, the sha256 of the compose file the step yields; a replacement's
kkt:substitutedBy is qualified by the candidate's content hash. A step is approved when every change set that recorded
it went through the review lane and a person other than its submitter approved it (api.review_decisions lists only
people's decisions).
"""
from __future__ import annotations

import hashlib
import re

PPLAN_STEP_OF = "http://purl.org/net/p-plan#isStepOfPlan"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
DCT_TYPE = "http://purl.org/dc/terms/type"
SOSA = "http://www.w3.org/ns/sosa/"
SUBSTITUTED_BY = "https://w3id.org/knowledge-kernel/tosca#substitutedBy"
CHECKSUM = "http://spdx.org/rdf/terms#checksumValue"
SHA256 = re.compile(r"[0-9a-f]{64}")


def steps(claims: list[dict], change_sets: dict[str, dict]) -> list[dict]:
    """claims: current claims about plan steps (id, subject, predicate, object_entity, object_value,
    qualifiers, change_set); change_sets: id -> {lane, decided_by, submitted_by, status} (api.review_decisions)."""
    by: dict[str, list[dict]] = {}
    for c in claims:
        by.setdefault(c["subject"], []).append(c)
    out = []
    for step, cs in sorted(by.items()):
        get = lambda p: next((c for c in cs if c["predicate"] == p), None)
        part = get(PPLAN_STEP_OF)
        if not part or not any(c["predicate"] == RDF_TYPE and c["object_entity"] == SOSA + "Actuation" for c in cs):
            continue
        action, target, result = get(DCT_TYPE), get(SOSA + "hasFeatureOfInterest"), get(SOSA + "hasSimpleResult")
        substitute = get(SUBSTITUTED_BY)
        preds = [c["predicate"] for c in cs]
        ambiguous = len({str(c["change_set"]) for c in cs}) > 1 or len(preds) != len(set(preds))
        approvals = [change_sets.get(str(c["change_set"]), {}) for c in cs]
        decided = [a.get("decided_at") for a in approvals if a.get("decided_at")]
        out.append({"step": step, "plan": part["object_entity"], "claims": sorted(str(c["id"]) for c in cs),
                    "change_sets": sorted({str(c["change_set"]) for c in cs}),
                    "action": action["object_entity"] if action else None,
                    "target": target["object_entity"] if target else None,
                    "value": (result["object_value"] or {}).get("@value") if result else None,
                    "candidate": substitute["object_entity"] if substitute else None,
                    "sha256": (substitute.get("qualifiers") or {}).get(CHECKSUM) if substitute else None,
                    "file_sha256": (result.get("qualifiers") or {}).get(CHECKSUM) if result else None,
                    "ambiguous": ambiguous,
                    "approved": bool(approvals) and all(a.get("lane") == "review" and a.get("decided_by")
                                                        and a["decided_by"] != a.get("submitted_by")
                                                        and a.get("status") == "applied" for a in approvals),
                    "decided_at": max(decided) if decided else None})
    return out


def system_of(target) -> str | None:
    """The system a step's target belongs to: urn:kk:system:<s>, or a node urn:kk:node:<s>:<service>."""
    m = re.fullmatch(r"urn:kk:(?:system:([a-z0-9][a-z0-9_.-]*)|node:([a-z0-9][a-z0-9_.-]*):[a-z0-9][a-z0-9_.-]*)",
                     target) if isinstance(target, str) else None
    return (m.group(1) or m.group(2)) if m else None


def approval(found: list[dict], labels: dict, acts: dict, system: str, text: bytes, base: bytes | None) -> dict | None:
    """The latest approved step that authorises `text` (a system's compose file, as committed) to run, as {decided_at,
    step, claims}, or None (T26). Nothing an agent wrote is trusted beyond what a person saw when deciding:
      a step on urn:kk:system:<system> (create, adopt) authorises the file whose sha256 is its value, and only when the
      plan's label, recorded in the same approved change set, shows that file's whole text;
      a setting step on a node of the system authorises the file the runtime derives itself: `base` (the file it last
      ran for the system) with the step's value set (morphogen.systems.with_setting), when the action is on the fixed
      list (`acts`, from the code, not from intent) and the value within its bounds. The step's own spdx:checksumValue
      is the planner's and actuator's, never the runtime's.
    labels: {(plan, change set id): the plan's label}; found: steps(...)."""
    from morphogen import systems
    sha = hashlib.sha256(text).hexdigest()
    try:
        shown = text.decode("utf-8")
    except UnicodeDecodeError:
        return None
    best = None
    for s in found:
        if not s["approved"] or s["ambiguous"] or system_of(s["target"]) != system:
            continue
        if s["target"].startswith("urn:kk:system:"):
            ok = s["value"] == sha and any(shown in (labels.get((s["plan"], cs)) or "") for cs in s["change_sets"])
        else:
            a = acts.get(s["action"]) or {}
            v = s["value"]
            ok = (a.get("kind", "setting") == "setting" and a.get("applies_to") == "node" and base is not None
                  and isinstance(v, (int, float)) and not isinstance(v, bool) and a["min"] <= v <= a["max"]
                  and (not a.get("integer") or v == int(v)))
            if ok:
                try:
                    derived = systems.with_setting(base.decode("utf-8"), s["target"].rsplit(":", 1)[1], a["setting"], v)[2]
                except (ValueError, UnicodeDecodeError):
                    derived = None
                ok = derived is not None and derived.encode("utf-8") == text
        if ok and (best is None or s["decided_at"] > best["decided_at"]):
            best = {"decided_at": s["decided_at"], "step": s["step"], "claims": s["claims"]}
    return best
