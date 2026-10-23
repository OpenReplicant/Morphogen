"""Approved plan steps -> edits to intent files (R5-07). Pure functions but for the file edit; no database.

A plan step is a sosa:Actuation that is p-plan:isStepOfPlan a plan, with dcterms:type an action from the
fixed list (intent/policies/actions.yaml), sosa:hasFeatureOfInterest a provider (urn:kk:provider:<name>)
and the new value as sosa:hasSimpleResult. A step is carried out only if
  every change set that recorded it went through the review lane and a person other than its submitter
  approved it (rebuild 4 actuator-compose's rule; api.review_decisions lists only people's decisions);
  one change set recorded it, with one value per predicate; the action is on the list; the provider has an intent
  file in this environment; the value is within the action's bounds; and this actuator has not run the
  step before. A replacement step must name the candidate's content hash, and the candidate's directory
  must still have it: what a person approved is what was measured.
Carrying it out sets the action's setting in the provider's intent file; the caller commits the file.
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from morphogen.experiments import candidate_dir, tree_hash

PPLAN_STEP_OF = "http://purl.org/net/p-plan#isStepOfPlan"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
DCT_TYPE = "http://purl.org/dc/terms/type"
SOSA = "http://www.w3.org/ns/sosa/"
SUBSTITUTED_BY = "https://w3id.org/knowledge-kernel/tosca#substitutedBy"
CHECKSUM = "http://spdx.org/rdf/terms#checksumValue"
SERVICE = re.compile(r"python3 -m [a-z_][a-z0-9_]*")


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
        out.append({"step": step, "plan": part["object_entity"], "claims": sorted(str(c["id"]) for c in cs),
                    "change_sets": sorted({str(c["change_set"]) for c in cs}),
                    "action": action["object_entity"] if action else None,
                    "target": target["object_entity"] if target else None,
                    "value": (result["object_value"] or {}).get("@value") if result else None,
                    "candidate": substitute["object_entity"] if substitute else None,
                    "sha256": (substitute.get("qualifiers") or {}).get(CHECKSUM) if substitute else None,
                    "ambiguous": ambiguous,
                    "approved": bool(approvals) and all(a.get("lane") == "review" and a.get("decided_by")
                                                        and a["decided_by"] != a.get("submitted_by")
                                                        and a.get("status") == "applied" for a in approvals)})
    return out


def intent_file(intent: Path, env: str, target) -> Path | None:
    """The environment's intent file for the provider: the one whose `provider:` names it, else <name>.yaml
    (a file keeps its name when another provider replaces the one it was written for)."""
    if not isinstance(target, str) or not target.startswith("urn:kk:provider:"):
        return None
    name = target.removeprefix("urn:kk:provider:")
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", name):
        return None
    files = sorted((intent / "environments" / env).glob("*.yaml"))
    named = [f for f in files if re.search(rf"^provider:[ \t]*{re.escape(name)}[ \t]*$", f.read_text(), re.M)]
    if named:
        return named[0] if len(named) == 1 else None
    f = intent / "environments" / env / f"{name}.yaml"
    return f if f.exists() and not re.search(r"^provider:", f.read_text(), re.M) else None


def refusal(s: dict, actions: dict, intent: Path, env: str) -> str | None:
    """Why the actuator will not carry out step s, or None."""
    if not s["approved"]:
        return "not approved by a person in the review lane"
    if s.get("ambiguous"):
        return "the step is recorded by more than one change set, or names a predicate twice"
    a = actions.get(s["action"])
    if a is None or a.get("kind", "setting") not in ("setting", "replace"):
        return f"the action {s['action']!r} is not on the fixed list of plan steps"
    if intent_file(intent, env, s["target"]) is None:
        return f"{s['target']!r} has no intent file in {env}"
    if a.get("kind") == "replace":
        d = candidate_dir(intent, s["candidate"]) if s.get("candidate") else None
        if d is None:
            return f"the candidate {s.get('candidate')!r} is not one experiment's provider"
        meta = yaml.safe_load((d / "provider.yaml").read_text()) or {}
        if not SERVICE.fullmatch(str(meta.get("service", ""))):
            return "the candidate's service must be python3 -m <module>"
        if not s.get("sha256"):
            return "the step names no content hash for the candidate"
        if tree_hash(d) != s["sha256"]:
            return "the candidate's directory is not the code that was measured and approved"
        return None
    v = s["value"]
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not a["min"] <= v <= a["max"]:
        return f"{a['setting']} must be a number from {a['min']:g} to {a['max']:g}"
    return None


def replace(intent: Path, f: Path, candidate: str) -> dict:
    """Point the intent file at the candidate: its provider name, service and directory; env stays."""
    d = candidate_dir(intent, candidate)
    meta = yaml.safe_load((d / "provider.yaml").read_text())
    text = f.read_text()
    before = {k: (m.group(1) if (m := re.search(rf"^{k}:[ \t]*(.*?)[ \t]*$", text, re.M)) else None)
              for k in ("provider", "service", "cwd")}
    after = {"provider": candidate.removeprefix("urn:kk:provider:"), "service": meta["service"],
             "cwd": str(d.relative_to(intent))}
    for k, v in after.items():
        line = re.compile(rf"^{k}:[ \t]*.*?[ \t]*$", re.M)
        text = line.sub(f"{k}: {v}", text, count=1) if line.search(text) else f"{k}: {v}\n" + text
    f.write_text(text)
    return {"before": before, "after": after}


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
