"""Approved plan steps -> edits to intent files (R5-07). Pure functions but for the file edit; no database.

A plan step is a sosa:Actuation that is p-plan:isStepOfPlan a plan, with dcterms:type an action from the
fixed list (intent/policies/actions.yaml), sosa:hasFeatureOfInterest a provider (urn:kk:provider:<name>)
and the new value as sosa:hasSimpleResult; an action with `applies_to: node` names a service of a managed
system instead (urn:kk:node:<system>:<service>, R5-25) and changes a setting its compose file already has.
A step is carried out only if
  every change set that recorded it went through the review lane and a person other than its submitter
  approved it (rebuild 4 actuator-compose's rule; api.review_decisions lists only people's decisions);
  one change set recorded it, with one value per predicate; the action is on the list; the provider has an intent
  file in this environment (a node: its system's compose file sets the action's setting); the value is within the action's bounds; and this actuator has not run the
  step before. A replacement step must name the candidate's content hash, and the candidate's directory
  must still have it: what a person approved is what was measured. A create step (R5-29) names a new system
(urn:kk:system:<name>) whose compose file does not exist yet, and the sha256 of the file the design agent
rendered: the actuator renders it again from the record and writes it only if it is the text approved.
A step on a node names the sha256 of the compose file it yields (its result's spdx:checksumValue), and the
actuator writes only that file. An adopt step names an existing system's file by its sha256 and writes nothing:
a person approved the file as committed (T26). A runtime runs only a file an approved step names.
Carrying it out sets the action's setting in the provider's intent file (or the node's compose file); the
caller commits the file.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

from morphogen import systems
from morphogen.plans import PPLAN_STEP_OF, steps  # noqa: F401 (steps: the actuator's reading of the record)
from morphogen.experiments import candidate_dir, tree_hash

SERVICE = re.compile(r"python3 -m [a-z_][a-z0-9_]*")


def new_system_file(intent: Path, target) -> Path | None:
    """intent/systems/<name>/compose.yaml for urn:kk:system:<name>, when neither it nor a link on its way exists."""
    m = re.fullmatch(r"urn:kk:system:([a-z0-9][a-z0-9_.-]*)", target) if isinstance(target, str) else None
    if not m:
        return None
    root = Path(intent) / "systems"
    d = root / m.group(1)
    if root.is_symlink() or d.is_symlink() or (d.exists() and not d.is_dir()):
        return None
    f = d / "compose.yaml"
    return None if f.exists() or f.is_symlink() else f


def system_file(intent: Path, target) -> Path | None:
    """intent/systems/<name>/compose.yaml for urn:kk:system:<name>, when it is a file and no link is on its way."""
    m = re.fullmatch(r"urn:kk:system:([a-z0-9][a-z0-9_.-]*)", target) if isinstance(target, str) else None
    if not m:
        return None
    root = (Path(intent) / "systems").resolve()
    f = Path(intent) / "systems" / m.group(1) / "compose.yaml"
    return f if f.is_file() and not f.is_symlink() and f.resolve().parent == root / m.group(1) else None


def target_file(intent: Path, env: str, target, action: dict) -> Path | None:
    """The file a step on `target` changes: a new system's compose file, the node's compose file, or the
    provider's intent file."""
    if action.get("kind") == "create":
        return new_system_file(intent, target)
    if action.get("kind") == "adopt":
        return system_file(intent, target)
    if action.get("applies_to", "provider") == "node":
        found = systems.compose_file(intent, target)
        return found[0] if found else None
    return intent_file(intent, env, target)


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
    if a is None or a.get("kind", "setting") not in ("setting", "replace", "create", "adopt"):
        return f"the action {s['action']!r} is not on the fixed list of plan steps"
    if a.get("kind") == "create":
        f = new_system_file(intent, s["target"])
        if f is None:
            return f"{s['target']!r} is not a new system's name, or its compose file exists already"
        if not isinstance(s["value"], str) or not re.fullmatch(r"[0-9a-f]{64}", s["value"]):
            return "the step names no sha256 for the file to write"
        return None
    if a.get("kind") == "adopt":
        f = system_file(intent, s["target"])
        if f is None:
            return f"{s['target']!r} is not a managed system with a compose file"
        if not isinstance(s["value"], str) or not re.fullmatch(r"[0-9a-f]{64}", s["value"]):
            return "the step names no sha256 for the file to run"
        if hashlib.sha256(f.read_bytes()).hexdigest() != s["value"]:     # bytes, as the runtime and encoder hash them
            return "the system's compose file is no longer the one approved"
        return None
    if a.get("applies_to", "provider") == "node":
        if systems.compose_file(intent, s["target"]) is None:
            return f"{s['target']!r} is not a service of a managed system"
        if systems.setting(intent, s["target"], a["setting"]) is None:
            return f"{s['target']!r} has no setting {a['setting']} in its compose file"
    elif intent_file(intent, env, s["target"]) is None:
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
    if a.get("integer") and v != int(v):
        return f"{a['setting']} must be a whole number"
    if a.get("applies_to", "provider") == "node":
        found = systems.compose_file(intent, s["target"])
        if not s.get("file_sha256"):
            return "the step names no sha256 of the compose file it yields"
        if systems.sha(systems.with_setting(found[0].read_text(), found[1], a["setting"], v)[2]) != s["file_sha256"]:
            return "the compose file the step yields is not the one approved: the file changed since the plan"
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
