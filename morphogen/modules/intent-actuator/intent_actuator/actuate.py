"""Approved plan steps -> edits to intent files (R5-07). Pure functions but for the file edit; no database.

A plan step is a sosa:Actuation that is p-plan:isStepOfPlan a plan, with dcterms:type an action from the
fixed list (intent/policies/actions.yaml), sosa:hasFeatureOfInterest a provider (urn:kk:provider:<name>)
and the new value as sosa:hasSimpleResult. A step is carried out only if
  every change set that recorded it went through the review lane and a person other than its submitter
  approved it (rebuild 4 actuator-compose's rule; api.review_decisions lists only people's decisions);
  one change set recorded it, with one value per predicate; the action is on the list; the provider has an intent
  file in this environment; the value is within the action's bounds; and this actuator has not run the
  step before.
Carrying it out sets the action's setting in the provider's intent file; the caller commits the file.
"""
from __future__ import annotations

import re
from pathlib import Path

PPLAN_STEP_OF = "http://purl.org/net/p-plan#isStepOfPlan"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
DCT_TYPE = "http://purl.org/dc/terms/type"
SOSA = "http://www.w3.org/ns/sosa/"


def steps(claims: list[dict], change_sets: dict[str, dict]) -> list[dict]:
    """claims: current claims about plan steps (id, subject, predicate, object_entity, object_value,
    change_set); change_sets: id -> {lane, decided_by, submitted_by, status} (api.review_decisions)."""
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
        preds = [c["predicate"] for c in cs]
        ambiguous = len({str(c["change_set"]) for c in cs}) > 1 or len(preds) != len(set(preds))
        approvals = [change_sets.get(str(c["change_set"]), {}) for c in cs]
        out.append({"step": step, "plan": part["object_entity"], "claims": sorted(str(c["id"]) for c in cs),
                    "change_sets": sorted({str(c["change_set"]) for c in cs}),
                    "action": action["object_entity"] if action else None,
                    "target": target["object_entity"] if target else None,
                    "value": (result["object_value"] or {}).get("@value") if result else None,
                    "ambiguous": ambiguous,
                    "approved": bool(approvals) and all(a.get("lane") == "review" and a.get("decided_by")
                                                        and a["decided_by"] != a.get("submitted_by")
                                                        and a.get("status") == "applied" for a in approvals)})
    return out


def intent_file(intent: Path, env: str, target) -> Path | None:
    if not isinstance(target, str) or not target.startswith("urn:kk:provider:"):
        return None
    name = target.removeprefix("urn:kk:provider:")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        return None
    f = intent / "environments" / env / f"{name}.yaml"
    return f if f.exists() else None


def refusal(s: dict, actions: dict, intent: Path, env: str) -> str | None:
    """Why the actuator will not carry out step s, or None."""
    if not s["approved"]:
        return "not approved by a person in the review lane"
    if s.get("ambiguous"):
        return "the step is recorded by more than one change set, or names a predicate twice"
    a = actions.get(s["action"])
    if a is None:
        return f"the action {s['action']!r} is not on the fixed list"
    if intent_file(intent, env, s["target"]) is None:
        return f"{s['target']!r} has no intent file in {env}"
    v = s["value"]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not a["min"] <= v <= a["max"]:
        return f"{a['setting']} must be a number from {a['min']:g} to {a['max']:g}"
    return None


def set_env(path: Path, name: str, value) -> tuple[str | None, str]:
    """Set `name` under the file's `env:` block to `value` (quoted), keeping everything else as written.
    Returns (the value before, or None; the value now)."""
    text = path.read_text()
    new = f'"{value:g}"' if isinstance(value, float) else f'"{value}"'
    line = re.compile(rf"^([ \t]+){re.escape(name)}:[ \t]*(.*?)[ \t]*$", re.M)
    m = line.search(text)
    if m:
        before = m.group(2).strip('"\'')
        text = text[:m.start()] + f"{m.group(1)}{name}: {new}" + text[m.end():]
    else:
        before = None
        env = re.search(r"^env:[ \t]*$", text, re.M)
        if env:
            text = text[:env.end()] + f"\n  {name}: {new}" + text[env.end():]
        else:
            text = text.rstrip("\n") + f"\nenv:\n  {name}: {new}\n"
    path.write_text(text)
    return before, new.strip('"')
