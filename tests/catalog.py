"""The test projects' authoring form, `{cells, interfaces, <settings>}`, as the catalog a project commits.

Fixtures keep a project as a plain dict so a test can change one field; `dump` turns it into the
`catalog-info.yaml` the judge reads: a Component per cell (a System for the root cell that carries the
settings), an API per interface, `spec.morphogen` holding the cell's rules and the settings.
"""

from __future__ import annotations

import yaml

from morphogen.backstage import SETTINGS

FILE = "catalog-info.yaml"
STRUCTURE_KEYS = ("in", "provides", "consumes", "owner", "lifecycle")   # Backstage's own fields; the rest are rules


def _listed(v):
    return [] if v is None else list(v) if isinstance(v, (list, tuple)) else [v]


def entities(doc: dict) -> list[dict]:
    cells, ifaces = doc.get("cells") or {}, doc.get("interfaces") or {}
    settings = {k: v for k, v in doc.items() if k in SETTINGS}
    roots = [n for n, c in cells.items() if not (c or {}).get("in")]
    holder = roots[0] if roots else None
    out = []
    for name, c in cells.items():
        c = dict(c or {})
        parent = c.get("in")
        kind = "System" if name == holder and settings else "Component"
        spec: dict = {"type": "service", "lifecycle": c.get("lifecycle", "experimental")}
        if "lifecycle" not in c:
            del spec["lifecycle"]
        if c.get("owner"):
            spec["owner"] = c["owner"]
        if parent:
            spec["subcomponentOf" if cells.get(parent) is not None and _kind(parent, cells, holder, settings) == "Component"
                  else "system"] = parent
        apis = [i for i in _listed(c.get("consumes")) if i not in cells or i in ifaces]
        deps = [i for i in _listed(c.get("consumes")) if i in cells and i not in ifaces]
        if c.get("provides"):
            spec["providesApis"] = _listed(c["provides"])
        if apis:
            spec["consumesApis"] = apis
        if deps:
            spec["dependsOn"] = [f"component:{d}" for d in deps]
        rules = {k: v for k, v in c.items() if k not in STRUCTURE_KEYS}
        if name == holder and settings:
            rules.update(settings)
        if rules:
            spec["morphogen"] = rules
        out.append({"apiVersion": "backstage.io/v1alpha1", "kind": kind, "metadata": {"name": name}, "spec": spec})
    if settings and holder is None:
        out.append({"apiVersion": "backstage.io/v1alpha1", "kind": "System", "metadata": {"name": "project"},
                    "spec": {"morphogen": dict(settings)}})
    for name, i in ifaces.items():
        i = {"tests": i} if isinstance(i, (str, list)) else dict(i or {})
        e = {"apiVersion": "backstage.io/v1alpha1", "kind": "API", "metadata": {"name": name},
             "spec": {"type": "openapi", **({"morphogen": i} if i else {})}}
        out.append(e)
    return out


def _kind(name, cells, holder, settings):
    return "System" if name == holder and settings else "Component"


def dump(doc: dict) -> str:
    """The catalog text (one file, one document per entity) for an authoring dict."""
    return yaml.safe_dump_all(entities(doc), sort_keys=False)


def project(doc: dict):
    """The Project the catalog written from `doc` compiles to (read from a temporary directory)."""
    import tempfile
    from pathlib import Path

    from morphogen.project import Project
    d = Path(tempfile.mkdtemp())
    (d / FILE).write_text(dump(doc))
    return Project.load(d)
