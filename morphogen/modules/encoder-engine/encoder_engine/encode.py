"""What a container engine runs -> node representations (R5-49). Pure functions; no engine, no database.

Input: `docker inspect` (or `podman inspect`) output for the containers of one compose project. Each running
container of a compose service becomes, for its system:

  urn:kk:representation:<system>:<service>  a kkt:NodeRepresentation ; rdfs:label <service> ;
                                            kkt:memberOf urn:kk:system:<system> ;
                                            kkt:representationOf urn:kk:node:<system>:<service> (the template it was
                                              created from, matched by name as TOSCA 2.0 matches them) ;
                                            kkt:propertyValue <value> {kkt:propertyName image | command | <ENV NAME>}

the same property names encoder-compose gives a template (image as written, the command's words joined by spaces,
each environment variable), so the kk-tosca drift shapes can compare the two. Every claim is observed and references
the container it was read from. A service with several containers is represented by the first by name; stopped
containers are not running and give nothing.

A command or an environment value is recorded as it runs only where it is what the system's compose file declares
(`declared`), so it is already in the record as the template's; any other is recorded as WITHHELD. What runs outside
the intent (a container started by hand, a password set at `docker run`) is what drift is for, and its values may be
secrets: the record learns that a setting differs, or exists, and never its value. The image is always recorded.
(The drift shapes compare a template's settings with what runs; a setting only the running container has is recorded,
withheld, but raises no drift yet.)
"""
from __future__ import annotations

import re
import shlex

import yaml

KKT = "https://w3id.org/knowledge-kernel/tosca#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
NAME = re.compile(r"[a-z0-9][a-z0-9_.-]*")
SERVICE = "com.docker.compose.service"
PROJECT = "com.docker.compose.project"
WITHHELD = "(withheld: not as the compose file declares it)"


def representation_iri(system: str, service: str) -> str:
    return f"urn:kk:representation:{system}:{service}"


def claim(subject: str, predicate: str, obj: dict, ref: list[dict], qualifiers: dict | None = None) -> dict:
    op = {"op": "add_claim", "subject": subject, "predicate": predicate, "object": obj, "evidence_type": "observed",
          "references": ref}
    if qualifiers:
        op["qualifiers"] = qualifiers
    return op


def words(command: str) -> list[str]:
    """A string command's words, as a shell splits them; on a quote left open, at spaces (encoder-compose does the same)."""
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def declared(text: str | None) -> dict[str, dict[str, str]]:
    """{service: {command | <ENV NAME>: value}} as encoder-compose records a compose file's settings (the scalars as
    written; a string command split as a shell splits it, as the engine runs it)."""
    if not text:
        return {}
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    pairs = lambda n: [(k.value, v) for k, v in n.value] if isinstance(n, yaml.MappingNode) else []  # noqa: E731
    out = {}
    for key, svc in pairs(next((v for k, v in pairs(root) if k == "services"), None)):
        got = dict(pairs(svc))
        settings = {}
        if isinstance(cmd := got.get("command"), yaml.ScalarNode):
            settings["command"] = " ".join(words(cmd.value))
        elif isinstance(cmd, yaml.SequenceNode):
            settings["command"] = " ".join(x.value for x in cmd.value if isinstance(x, yaml.ScalarNode))
        env = got.get("environment")
        if isinstance(env, yaml.MappingNode):
            settings.update((k, v.value if isinstance(v, yaml.ScalarNode) else "") for k, v in pairs(env))
        elif isinstance(env, yaml.SequenceNode):
            settings.update(x.value.split("=", 1) for x in env.value if isinstance(x, yaml.ScalarNode) and "=" in x.value)
        out[key] = settings
    return out


def representations(system: str, project: str, containers: list[dict], engine: str = "docker",
                    intended: dict[str, dict[str, str]] | None = None) -> list[dict]:
    """`intended`: the compose file's settings (`declared`); a value not among them is WITHHELD."""
    if not NAME.fullmatch(system):
        raise ValueError(f"system name {system!r}: lower case letters, digits, _ . -")
    chosen: dict[str, dict] = {}
    for c in sorted(containers, key=lambda c: c.get("Name", "")):
        labels = (c.get("Config") or {}).get("Labels") or {}
        service = labels.get(SERVICE)
        if labels.get(PROJECT) != project or not (c.get("State") or {}).get("Running") or not service:
            continue
        if NAME.fullmatch(service):
            chosen.setdefault(service, c)
    ops = []
    for service, c in sorted(chosen.items()):
        cfg = c.get("Config") or {}
        r = representation_iri(system, service)
        ref = [{"source_uri": f"urn:kk:engine:{engine}:container:{c['Id']}"}]
        ops += [claim(r, RDF_TYPE, {"entity": KKT + "NodeRepresentation"}, ref),
                claim(r, LABEL, {"value": {"@value": service}}, ref),
                claim(r, KKT + "memberOf", {"entity": f"urn:kk:system:{system}"}, ref),
                claim(r, KKT + "representationOf", {"entity": f"urn:kk:node:{system}:{service}"}, ref)]
        want = (intended or {}).get(service, {})
        prop = lambda name, value: claim(r, KKT + "propertyValue", {"value": {"@value": value}}, ref,  # noqa: E731
                                         {KKT + "propertyName": name})
        kept = lambda name, value: prop(name, value if want.get(name) == value else WITHHELD)  # noqa: E731
        if cfg.get("Image"):
            ops.append(prop("image", cfg["Image"]))
        if cfg.get("Cmd"):
            ops.append(kept("command", " ".join(cfg["Cmd"])))
        env = dict(e.split("=", 1) for e in cfg.get("Env") or [] if "=" in e)
        ops += [kept(k, v) for k, v in sorted(env.items())]
    return ops
