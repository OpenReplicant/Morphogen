"""Backstage's catalog as a source of cells: `catalog-info.yaml` files read directly, with no Backstage
server.

    morphogen.yaml:  backstage: catalog-info.yaml        # or a list; paths inside the project

| Backstage                                       | Becomes                                         |
|-------------------------------------------------|-------------------------------------------------|
| Component, System, Domain                       | a cell, named by its ref (component:default/x)  |
| subcomponentOf, system, domain, subdomainOf     | `in`                                            |
| API                                             | an interface, named by its ref                  |
| providesApis, consumesApis                      | provides, consumes                              |
| dependsOn X                                     | consumes X: provided by X if X is a cell, else external (a Resource) |
| Location targets                                | more files to read (relative paths inside the project) |
| annotations morphogen.dev/change, keep, run, better, tests, score, dir, observe | the cell's fields; on an API, morphogen.dev/tests are its tests |

Refs follow Backstage: `[kind:][namespace/]name`, lowercased; an omitted namespace is the entity's
own, and an omitted kind is the field's default (Component for subcomponentOf and dependsOn, System,
Domain, API for the API lists). An annotation that lists several entries (`change`, `keep`,
`tests`) puts one per line. Fields Backstage defines that Morphogen does not use (owner, lifecycle,
type, definition, links, tags) are ignored, as are kinds without a structural meaning here (Group,
User, Template).
"""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import Any

import yaml

CELL_KINDS = ("component", "system", "domain")
ANNOTATION = "morphogen.dev/"
CELL_FIELDS = ("change", "keep", "run", "better", "tests", "score", "dir", "observe")
LISTED = ("change", "keep", "tests")


class CatalogError(ValueError):
    pass


def parse_ref(ref: str, default_kind: str, namespace: str = "default") -> str:
    """`[kind:][namespace/]name` -> `kind:namespace/name`, lowercased."""
    if not isinstance(ref, str) or not ref.strip():
        raise CatalogError(f"an empty entity reference ({ref!r})")
    ref = ref.strip()
    kind, sep, rest = ref.partition(":")
    if not sep:
        kind, rest = default_kind, ref
    ns, sep, name = rest.partition("/")
    if not sep:
        ns, name = namespace, rest
    if not kind or not ns or not name:
        raise CatalogError(f"entity reference {ref!r}: write [kind:][namespace/]name")
    return f"{kind}:{ns}/{name}".lower()


def is_ref(text: str) -> bool:
    kind, sep, rest = text.partition(":")
    return bool(sep) and kind.lower() in CELL_KINDS + ("api", "resource")


def _inside(root: Path, rel: str, what: str) -> Path:
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts or "://" in rel:
        raise CatalogError(f"{what} {rel!r}: give a relative path inside the project")
    return root / p


def read(root: Path, files: list[str]) -> tuple[list[dict], list[str]]:
    """Every entity in `files` and the Location targets they name (each file read once), with the
    project-relative paths read."""
    root = Path(root)
    entities, seen, queue = [], [], [(f, "backstage") for f in files]
    while queue:
        rel, what = queue.pop(0)
        path = _inside(root, rel, what)
        key = str(PurePosixPath(rel))
        if key in seen:
            continue
        seen.append(key)
        try:
            docs = [d for d in yaml.safe_load_all(path.read_text()) if d is not None]
        except OSError as e:
            raise CatalogError(f"{rel}: cannot read ({e.strerror or e})") from None
        except yaml.YAMLError as e:
            raise CatalogError(f"{rel}: not valid YAML ({e})") from None
        for d in docs:
            if not isinstance(d, dict) or not d.get("kind") or not (d.get("metadata") or {}).get("name"):
                raise CatalogError(f"{rel}: an entity needs kind and metadata.name")
            d = {**d, "_file": key}
            entities.append(d)
            if str(d["kind"]).lower() == "location":
                spec = d.get("spec") or {}
                targets = list(spec.get("targets") or []) + ([spec["target"]] if spec.get("target") else [])
                base = PurePosixPath(rel).parent
                for t in targets:
                    if not isinstance(t, str):
                        raise CatalogError(f"{rel}: Location targets are strings")
                    joined = PurePosixPath(*(base / t).parts)
                    parts: list[str] = []
                    for part in joined.parts:   # normalise ./ and a/../ within the project
                        if part == "..":
                            if not parts:
                                raise CatalogError(f"{rel}: Location target {t!r} leaves the project")
                            parts.pop()
                        elif part != ".":
                            parts.append(part)
                    queue.append(("/".join(parts), f"{rel}: Location target"))
    return entities, seen


def _lines(v: Any) -> list[str]:
    if not isinstance(v, str):
        raise CatalogError(f"annotation values are strings, not {type(v).__name__}")
    return [x.strip() for x in v.splitlines() if x.strip()]


def to_cells(entities: list[dict]) -> tuple[dict, dict, dict[str, str]]:
    """(cells, interfaces, the file each came from), in the cell format's dict form."""
    cells: dict[str, dict] = {}
    interfaces: dict[str, dict] = {}
    origin: dict[str, str] = {}
    provides: dict[str, set] = {}
    for e in entities:
        kind = str(e["kind"]).lower()
        md, spec = e.get("metadata") or {}, e.get("spec") or {}
        ns = str(md.get("namespace") or "default").lower()
        me = parse_ref(md["name"], kind, ns)
        notes = {k[len(ANNOTATION):]: v for k, v in (md.get("annotations") or {}).items()
                 if k.startswith(ANNOTATION)}
        if kind == "api":
            entry: dict = {}
            if "tests" in notes:
                entry["tests"] = _lines(notes.pop("tests"))
            if notes:
                raise CatalogError(f"{me}: on an API, only {ANNOTATION}tests is read (not {', '.join(notes)})")
            interfaces[me] = entry
            origin[me] = e["_file"]
            continue
        if kind not in CELL_KINDS:
            continue
        cell: dict = {}
        parent = {"component": spec.get("subcomponentOf") and parse_ref(spec["subcomponentOf"], "component", ns)
                   or spec.get("system") and parse_ref(spec["system"], "system", ns),
                   "system": spec.get("domain") and parse_ref(spec["domain"], "domain", ns),
                   "domain": spec.get("subdomainOf") and parse_ref(spec["subdomainOf"], "domain", ns)}[kind]
        if parent:
            cell["in"] = parent
        if md.get("description"):
            cell["description"] = str(md["description"])
        prov = [parse_ref(r, "api", ns) for r in spec.get("providesApis") or []]
        cons = [parse_ref(r, "api", ns) for r in spec.get("consumesApis") or []]
        cons += [parse_ref(r, "component", ns) for r in spec.get("dependsOn") or []]
        if prov:
            cell["provides"] = prov
        if cons:
            cell["consumes"] = cons
        for k, v in notes.items():
            if k not in CELL_FIELDS:
                raise CatalogError(f"{me}: unknown annotation {ANNOTATION}{k} ({', '.join(CELL_FIELDS)})")
            cell[k] = _lines(v) if k in LISTED else v
        if me in cells:
            raise CatalogError(f"{me} is defined twice ({origin[me]}, {e['_file']})")
        cells[me] = cell
        origin[me] = e["_file"]
        provides[me] = set(prov)
    # An interface named by a cell's ref (a dependsOn, or a component listed as an API) is that cell;
    # one that names neither a cell nor an API is outside the catalog (a Resource, say).
    for name, cell in cells.items():
        for i in cell.get("consumes", []):
            if i in interfaces:
                continue
            if i in cells:
                cells[i].setdefault("provides", [])
                if i not in cells[i]["provides"]:
                    cells[i]["provides"].append(i)
                interfaces[i] = {}
            else:
                interfaces[i] = {"external": "provides"}
            origin.setdefault(i, origin[name])
    return cells, interfaces, origin
