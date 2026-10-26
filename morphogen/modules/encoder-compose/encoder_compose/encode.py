"""A compose file -> a TOSCA topology as claims (T9, R5-25). Pure functions; no database.

  urn:kk:system:<system>          rdf:type kkt:ServiceTemplate ; rdfs:label <system>        (the services: line)
  urn:kk:node:<system>:<service>  rdf:type kkt:NodeTemplate ; rdfs:label ; kkt:memberOf the system  (its key)
                                  kkt:propertyValue <value> {kkt:propertyName: image | command | <ENV NAME>}
                                  kkt:connectsTo urn:kk:node:<system>:<other>   (a URL in its command or environment
                                  whose host is another service, else a depends_on entry: the first is cited)

Every claim is deterministic and cites the file and the line its fact is written on (a FragmentSelector
`line=N`, RFC 5147), taken from the YAML parser's own positions, never from a text search. Ports,
volumes and networks are not encoded yet.
"""
from __future__ import annotations

import re
import shlex

import yaml

RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
KKT = "https://w3id.org/knowledge-kernel/tosca#"
NAME = re.compile(r"[a-z0-9][a-z0-9_.-]*")


def system_iri(system: str) -> str:
    return f"urn:kk:system:{system}"


def node_iri(system: str, service: str) -> str:
    return f"urn:kk:node:{system}:{service}"


def ref(rel: str, node: yaml.Node) -> list[dict]:
    return [{"source_uri": f"file:{rel}", "span": {"type": "FragmentSelector", "value": f"line={node.start_mark.line + 1}",
                                                   "conformsTo": "https://www.rfc-editor.org/rfc/rfc5147"}}]


def claim(subject: str, predicate: str, obj: dict, refs: list[dict], qualifiers: dict | None = None) -> dict:
    c = {"op": "add_claim", "subject": subject, "predicate": predicate, "object": obj,
         "evidence_type": "deterministic", "references": refs}
    if qualifiers:
        c["qualifiers"] = qualifiers
    return c


def mapping(node: yaml.Node) -> list[tuple[yaml.Node, yaml.Node]]:
    return node.value if isinstance(node, yaml.MappingNode) else []


def get(node: yaml.Node, key: str):
    return next((v for k, v in mapping(node) if k.value == key), None)


def scalars(node) -> list[yaml.ScalarNode]:
    if isinstance(node, yaml.ScalarNode):
        return [node]
    if isinstance(node, yaml.SequenceNode):
        return [n for n in node.value if isinstance(n, yaml.ScalarNode)]
    return []


def split(command: str) -> list[str]:
    """A string command's words, as a shell splits them; on a quote left open, at spaces (encoder-engine does the same)."""
    try:
        return shlex.split(command)
    except ValueError:
        return command.split()


def environment(node) -> list[tuple[str, str, yaml.Node]]:
    """(name, value, node to cite) for a mapping or a list of NAME=value."""
    if isinstance(node, yaml.MappingNode):
        return [(k.value, v.value if isinstance(v, yaml.ScalarNode) else "", k) for k, v in node.value]
    return [(*n.value.split("=", 1), n) for n in scalars(node) if "=" in n.value]


def compose(rel: str, text: str, system: str) -> list[dict]:
    if not NAME.fullmatch(system):
        raise ValueError(f"system name {system!r}: lower case letters, digits, _ . -")
    root = yaml.compose(text, Loader=yaml.SafeLoader)
    services = next(((k, v) for k, v in mapping(root) if k.value == "services"), None)
    if services is None:
        raise ValueError(f"{rel}: no services")
    s = system_iri(system)
    ops = [claim(s, RDF_TYPE, {"entity": KKT + "ServiceTemplate"}, ref(rel, services[0])),
           claim(s, LABEL, {"value": {"@value": system}}, ref(rel, services[0]))]
    names = [k.value for k, _ in mapping(services[1])]
    for key, svc in mapping(services[1]):
        if not NAME.fullmatch(key.value):
            raise ValueError(f"{rel}: service name {key.value!r}")
        n, at = node_iri(system, key.value), ref(rel, key)
        ops += [claim(n, RDF_TYPE, {"entity": KKT + "NodeTemplate"}, at),
                claim(n, LABEL, {"value": {"@value": key.value}}, at),
                claim(n, KKT + "memberOf", {"entity": s}, at)]
        prop = lambda name, value, node: claim(n, KKT + "propertyValue", {"value": {"@value": value}}, ref(rel, node),
                                               {KKT + "propertyName": name})
        if (image := get(svc, "image")) is not None:
            ops.append(prop("image", image.value, image))
        command = get(svc, "command")
        if command is not None:
            words = split(command.value) if isinstance(command, yaml.ScalarNode) else [x.value for x in scalars(command)]
            ops.append(prop("command", " ".join(words), command))   # a string split as a shell does, as the engine runs it
        env = environment(get(svc, "environment"))
        ops += [prop(name, value, node) for name, value, node in env]
        links: dict[str, yaml.Node] = {}
        for words, node in [(x.value, x) for x in scalars(command)] + [(value, node) for _, value, node in env]:
            for host in re.findall(r"//([a-z0-9][a-z0-9_.-]*)(?=[:/]|$)", words):
                if host in names and host != key.value:
                    links.setdefault(host, node)
        dep = get(svc, "depends_on")
        for d in (scalars(dep) if not isinstance(dep, yaml.MappingNode) else [k for k, _ in dep.value]):
            links.setdefault(d.value, d)
        ops += [claim(n, KKT + "connectsTo", {"entity": node_iri(system, other)}, ref(rel, node))
                for other, node in sorted(links.items()) if other in names]
    return ops


ADOPT = "urn:kk:action:adopt-system"
PPLAN, SOSA, DCT_TYPE = "http://purl.org/net/p-plan#", "http://www.w3.org/ns/sosa/", "http://purl.org/dc/terms/type"


def adopt(rel: str, text: str, system: str, sha: str) -> tuple[str, list[dict]]:
    """(plan iri, ops): a plan with one step asking a person to approve the file as committed (T26); every claim
    cites the file by its content hash, and the label shows the whole file, so what is approved is what runs."""
    plan = f"urn:kk:plan:adopt:{system}:{sha[:16]}"
    step = f"{plan}:step:1"
    refs = [{"source_uri": f"file:{rel}#sha256={sha}"}]
    label = f"Run intent/systems/{system}/compose.yaml as committed (sha256 {sha}):\n\n{text}"
    return plan, [claim(plan, RDF_TYPE, {"entity": PPLAN + "Plan"}, refs),
                  claim(plan, LABEL, {"value": {"@value": label}}, refs),
                  claim(plan, DCT_TYPE, {"entity": "urn:kk:risk:medium"}, refs),
                  claim(step, RDF_TYPE, {"entity": SOSA + "Actuation"}, refs),
                  claim(step, PPLAN + "isStepOfPlan", {"entity": plan}, refs),
                  claim(step, DCT_TYPE, {"entity": ADOPT}, refs),
                  claim(step, SOSA + "hasFeatureOfInterest", {"entity": system_iri(system)}, refs),
                  claim(step, SOSA + "hasSimpleResult", {"value": {"@value": sha}}, refs)]
