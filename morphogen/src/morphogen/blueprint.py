"""From a described system to its compose file (R5-29): the design agent's blueprint, shared by the proposer
(design-blueprint) and the intent actuator, so both render the same text from the same record.

  MAP                                  the query for a system's current map claims (any agent's)
  described(claims, system)            -> {service: {image, command, environment, connects}}, or raises Conflict
  render(services, system)             -> the compose file's text (deterministic)
  sha(text)                            -> its sha256, which the plan step names
  label(system, text)                  -> the plan's label: what a person reads and approves, the file's whole text
  PROPOSER                             -> the only agent whose create plans the actuator carries out

The map is the one encoder-compose records and an interview describes (urn:kk:system:<name>, its
kkt:NodeTemplate services, their kkt:propertyValue settings named by kkt:propertyName, kkt:connectsTo).
Rendered: `image` and `command` as themselves, every other setting under `environment`, a connection as
`depends_on`, so encoder-compose's map of the file is the described map. Two current claims giving one
setting different values is a conflict a person settles first; the same value twice (described, then
encoded) is one setting.
"""
from __future__ import annotations

import hashlib
import re

import yaml

KKT = "https://w3id.org/knowledge-kernel/tosca#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
NAME = re.compile(r"[a-z0-9][a-z0-9_.-]*")
MAP = """select id, subject, predicate, object_entity, object_value, qualifiers from api.claims
         where status <> 'deprecated' and predicate = any(%(preds)s) and subject in
           (select subject from api.claims where predicate = %(member)s and object_entity = %(system)s
              and status <> 'deprecated')"""


PROPOSER = "urn:kk:agent:design-blueprint"
ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class Conflict(ValueError):
    pass


def params(system: str) -> dict:
    return {"preds": [RDF_TYPE, KKT + "memberOf", KKT + "propertyValue", KKT + "connectsTo"],
            "member": KKT + "memberOf", "system": f"urn:kk:system:{system}"}


def described(claims: list[dict], system: str) -> dict:
    prefix = f"urn:kk:node:{system}:"
    services: dict[str, dict] = {}
    for c in claims:
        if c["predicate"] == RDF_TYPE and c.get("object_entity") == KKT + "NodeTemplate" and c["subject"].startswith(prefix):
            name = c["subject"].removeprefix(prefix)
            if not NAME.fullmatch(name):
                raise Conflict(f"service name {name!r}")
            services.setdefault(name, {"settings": {}, "connects": set()})
    for c in claims:
        name = c["subject"].removeprefix(prefix)
        if name not in services:
            continue
        if c["predicate"] == KKT + "propertyValue":
            key = (c.get("qualifiers") or {}).get(KKT + "propertyName")
            if not isinstance(key, str) or not (key in ("image", "command") or ENV_NAME.fullmatch(key)):
                raise Conflict(f"{name}: a setting with no usable name ({key!r}; the qualifier key must be the full "
                               "kkt:propertyName IRI, the name an environment variable's)")
            value = str((c.get("object_value") or {}).get("@value"))
            seen = services[name]["settings"].get(key)
            if seen is not None and seen != value:
                raise Conflict(f"{name}: {key} is both {seen!r} and {value!r}")
            services[name]["settings"][key] = value
        elif c["predicate"] == KKT + "connectsTo":
            if not str(c.get("object_entity") or "").startswith(prefix):
                raise Conflict(f"{name} connects to {c.get('object_entity')}, outside the system: a compose file cannot say so")
            peer = c["object_entity"].removeprefix(prefix)
            if peer not in services:
                raise Conflict(f"{name} connects to {peer}, which is not one of the system's services")
            services[name]["connects"].add(peer)
    if not services:
        raise Conflict(f"no services described for {system}")
    out = {}
    for name, d in sorted(services.items()):
        s = dict(d["settings"])
        out[name] = {"image": s.pop("image", None), "command": s.pop("command", None),
                     "environment": dict(sorted(s.items())), "connects": sorted(d["connects"])}
    return out


def render(services: dict, system: str) -> str:
    doc = {}
    for name, d in services.items():
        svc = {}
        if d.get("image"):
            svc["image"] = d["image"]
        if d.get("command"):
            svc["command"] = d["command"]
        if d.get("environment"):
            svc["environment"] = {k: str(v) for k, v in d["environment"].items()}
        if d.get("connects"):
            svc["depends_on"] = list(d["connects"])
        doc[name] = svc
    head = (f"# {system}: written by Morphogen's design agent from the system a person described (R5-29).\n"
            "# Edit through Morphogen: a change here is a change to intent.\n")
    return head + yaml.safe_dump({"services": doc}, sort_keys=False, default_flow_style=False, width=1000)


def label(system: str, text: str) -> str:
    return f"Write intent/systems/{system}/compose.yaml, as described:\n\n{text}"


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()
