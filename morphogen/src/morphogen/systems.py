"""Systems Morphogen manages but did not build (R5-25): each is `intent/systems/<name>/compose.yaml`, and
each of its services is the node `urn:kk:node:<name>:<service>` (encoder-compose records the same IRIs).

  compose_file(intent, node)           -> (file, service) or None
  setting(intent, node, name)          -> the service's environment value of `name`, or None
  set_setting(intent, node, name, v)   -> (before, after): rewrites that one value where it is written

Only a setting the file already has is changed, and only its value's characters (located by the YAML
parser), so the rest of the file stays as the operator wrote it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

NODE = re.compile(r"urn:kk:node:([a-z0-9][a-z0-9_.-]*):([a-z0-9][a-z0-9_.-]*)")


def compose_file(intent: Path, node) -> tuple[Path, str] | None:
    m = NODE.fullmatch(node) if isinstance(node, str) else None
    if not m:
        return None
    f = Path(intent) / "systems" / m.group(1) / "compose.yaml"
    if not f.is_file() or f.is_symlink():
        return None
    services = (yaml.safe_load(f.read_text()) or {}).get("services") or {}
    return (f, m.group(2)) if m.group(2) in services else None


def _value_node(text: str, service: str, name: str) -> yaml.ScalarNode | None:
    """The scalar node of `name` in the service's environment mapping (list-form entries are not edited)."""
    get = lambda node, key: next((v for k, v in (node.value if isinstance(node, yaml.MappingNode) else [])
                                  if isinstance(k, yaml.ScalarNode) and k.value == key), None)
    env = get(get(get(yaml.compose(text, Loader=yaml.SafeLoader), "services"), service), "environment")
    v = get(env, name)
    return v if isinstance(v, yaml.ScalarNode) else None


def setting(intent: Path, node: str, name: str) -> str | None:
    found = compose_file(intent, node)
    if not found:
        return None
    v = _value_node(found[0].read_text(), found[1], name)
    return v.value if v is not None else None


def set_setting(intent: Path, node: str, name: str, value) -> tuple[str, str]:
    """Rewrite the setting's value (double-quoted, as compose wants strings); ValueError when the service
    or the setting is not there."""
    found = compose_file(intent, node)
    if not found:
        raise ValueError(f"{node} is not a service of a managed system")
    f, service = found
    text = f.read_text()
    v = _value_node(text, service, name)
    if v is None:
        raise ValueError(f"{node} has no environment setting {name} to change")
    new = f"{value:g}" if isinstance(value, float) else str(value)
    text = text[:v.start_mark.index] + json.dumps(new) + text[v.end_mark.index:]
    f.write_text(text)
    return v.value, new
