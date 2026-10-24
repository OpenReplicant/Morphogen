"""What the planner, builder, sandbox and actuator agree on about experiments (T6, R5-21).

  experiment_id(request)          the experiment directory a build request gets: intent/experiments/<id>
  run_name(id, role)              the evaluator run of the incumbent or the candidate in it
  provider_dir(provider)          a provider's directory, from its id (Morphogen's modules, then the kernel's)
  provider_slots(provider)        the slots a provider says it fills
  candidate_dir(intent, provider) a candidate's directory in an experiment, from its id
  tree_hash(dir)                  a provider directory's content hash (the builder records it; the plan
                                  carries it; the actuator checks it)
  check_candidate(dir, slot, ...) what makes a directory a candidate for a slot (the builder's and the
                                  catalog lookup's)
  build_requests(cur)             the planner's current build requests: {iri, target, slot, text, claims}
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
NAME = re.compile(r"[a-z0-9][a-z0-9-]*")
EXPERIMENT = re.compile(r"x[0-9a-f]{12}")
DCT, OA = "http://purl.org/dc/terms/", "http://www.w3.org/ns/oa#"
BUILD = "urn:kk:action:build-candidate"


def experiment_id(request: str) -> str:
    return "x" + hashlib.sha256(request.encode()).hexdigest()[:12]


def tree_hash(d: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(x for x in d.rglob("*") if x.is_file() and "__pycache__" not in x.parts):
        h.update(str(p.relative_to(d)).encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()


def run_name(exp_id: str, role: str) -> str:
    return f"{exp_id}-{role}"


def _meta(d: Path) -> dict:
    f = d / "provider.yaml"
    return (yaml.safe_load(f.read_text()) or {}) if f.exists() else {}


def provider_dir(provider: str) -> Path | None:
    name = provider.removeprefix("urn:kk:provider:")
    if name == provider or not NAME.fullmatch(name):
        return None
    for base in (ROOT / "morphogen" / "modules", ROOT / "kernel" / "providers"):
        if _meta(base / name).get("id") == provider:
            return base / name
    return None


def provider_slots(provider: str) -> list[str]:
    d = provider_dir(provider)
    return list(_meta(d).get("slots") or []) if d else []


def candidate_dir(intent: Path, provider: str) -> Path | None:
    """The one directory under intent/experiments/<id>/ whose provider.yaml has this id."""
    found = [d for exp in sorted((intent / "experiments").glob("x*")) if EXPERIMENT.fullmatch(exp.name)
             for d in sorted(exp.iterdir()) if d.is_dir() and NAME.fullmatch(d.name) and _meta(d).get("id") == provider]
    return found[0] if len(found) == 1 else None


def check_candidate(d: Path, slot: str, incumbent_id: str, incumbent: Path | None = None) -> dict:
    meta = yaml.safe_load((d / "provider.yaml").read_text()) if (d / "provider.yaml").exists() else None
    if not isinstance(meta, dict):
        raise ValueError("the candidate has no provider.yaml")
    if slot not in (meta.get("slots") or []):
        raise ValueError(f"the candidate does not fill {slot}")
    if not meta.get("service"):
        raise ValueError("the candidate needs a service")
    if incumbent is not None:
        mine, theirs = d / "migration.sql", incumbent / "migration.sql"
        if mine.exists() and (not theirs.exists() or mine.read_bytes() != theirs.read_bytes()):
            raise ValueError("the candidate's migration.sql differs from the incumbent's")
    cid = str(meta.get("id", ""))
    if cid == incumbent_id or not cid.startswith("urn:kk:provider:") or not NAME.fullmatch(cid.removeprefix("urn:kk:provider:")):
        raise ValueError(f"the candidate needs an id of its own, not {cid!r}")
    return meta


def build_requests(cur) -> list[dict]:
    cur.execute("""select subject, predicate, object_entity, object_value->>'@value', id from api.claims
                   where subject in (select subject from api.claims where predicate = %s and object_entity = %s
                                     and status <> 'deprecated')
                     and status <> 'deprecated'""", (DCT + "type", BUILD))
    out: dict[str, dict] = {}
    for s, p, oe, ov, cid in cur.fetchall():
        r = out.setdefault(s, {"iri": s, "claims": []})
        r["claims"].append(str(cid))
        if p == OA + "hasTarget":
            r["target"] = oe
        elif p == DCT + "subject":
            r["slot"] = oe
        elif p == OA + "bodyValue":
            r["text"] = ov
    return [r for r in out.values() if r.get("target") and r.get("slot") and r.get("text")]
