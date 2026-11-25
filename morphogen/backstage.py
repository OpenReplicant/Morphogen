"""The project's catalog: Backstage `catalog-info.yaml` files read directly, with no Backstage server.

The root is `catalog-info.yaml` at the repository root (Backstage's convention). It may be a
`Location` whose targets name more files inside the project; every file read this way is a rule file
(project.py: the judge reads it from the base commit, and a candidate may not change it).

| Backstage                                       | Becomes                                         |
|-------------------------------------------------|-------------------------------------------------|
| Component, System, Domain                       | a cell, named by its name (`ns/name` outside `default`) |
| subcomponentOf, system, domain, subdomainOf     | `in`                                            |
| API                                             | an interface, named the same way                |
| providesApis, consumesApis                      | provides, consumes                              |
| dependsOn X                                     | consumes X: provided by X if X is a cell, else external (a Resource) |
| Location targets                                | more files to read (relative paths inside the project) |
| owner, lifecycle                                | the cell's owner and lifecycle (what `autonomy` keys on) |
| `spec.morphogen` on a Component/System/Domain   | the cell's rules (project.CellRules)            |
| `spec.morphogen` on an API                      | the interface's `tests` and `external`          |
| `spec.morphogen` on the System                  | the project's settings and `defaults` (at most one System carries them) |

Refs follow Backstage: `[kind:][namespace/]name`, lowercased; an omitted namespace is the entity's
own, and an omitted kind is the field's default (Component for subcomponentOf and dependsOn, System,
Domain, API for the API lists). A cell is named by its `metadata.name` in the `default` namespace
and `namespace/name` elsewhere, whatever its kind, so two cell entities may not share a name.
Options (`spec.lifecycle: candidate`) and roles (`spec.type: role`) are never cells. Fields Backstage
defines that Morphogen does not use (type, definition, links, tags) are ignored, as are kinds without a
structural meaning here (Group, User, Template).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

CELL_KINDS = ("component", "system", "domain", "airesource")
ROOT = "catalog-info.yaml"
SETTINGS = ("trunk", "sandbox", "sandbox_image", "budget", "autonomy", "defaults")   # on the System only


class CatalogError(ValueError):
    pass


def _parts(ref: str, default_kind: str, namespace: str = "default") -> tuple[str, str, str]:
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
    return kind.lower(), ns.lower(), name.lower()


def parse_ref(ref: str, default_kind: str, namespace: str = "default") -> str:
    """`[kind:][namespace/]name` -> `kind:namespace/name`, lowercased (Backstage's full form)."""
    kind, ns, name = _parts(ref, default_kind, namespace)
    return f"{kind}:{ns}/{name}"


def ref_name(ref: str, default_kind: str, namespace: str = "default") -> str:
    """The name a reference has in a project: `name` in the default namespace, `ns/name` elsewhere; a kind
    that is neither a cell's nor an API's (a Resource) stays in front (`resource:db`), as it is outside the catalog."""
    kind, ns, name = _parts(ref, default_kind, namespace)
    own = name if ns == "default" else f"{ns}/{name}"
    return own if kind in CELL_KINDS + ("api",) else f"{kind}:{own}"


def _inside(rel: str, what: str) -> PurePosixPath:
    p = PurePosixPath(rel)
    if p.is_absolute() or ".." in p.parts or "://" in rel:
        raise CatalogError(f"{what} {rel!r}: give a relative path inside the project")
    return p


def fs_reader(root: Path) -> Callable[[str], str]:
    root = Path(root)
    return lambda rel: (root / rel).read_text()


def read(files: list[str], read_text: Callable[[str], str]) -> tuple[list[dict], list[str]]:
    """Every entity in `files` and the Location targets they name (each file read once through
    `read_text`, which takes a project-relative path), with the project-relative paths read: the rule files."""
    entities, seen, queue = [], [], [(f, "catalog") for f in files]
    while queue:
        rel, what = queue.pop(0)
        key = str(_inside(rel, what))
        if key in seen:
            continue
        seen.append(key)
        try:
            docs = [d for d in yaml.safe_load_all(read_text(key)) if d is not None]
        except OSError as e:
            raise CatalogError(f"{rel}: cannot read ({getattr(e, 'strerror', None) or e})") from None
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
                base = PurePosixPath(key).parent
                for t in targets:
                    if not isinstance(t, str):
                        raise CatalogError(f"{rel}: Location targets are strings")
                    parts: list[str] = []
                    for part in (base / t).parts:   # normalise ./ and a/../ within the project
                        if part == "..":
                            if not parts:
                                raise CatalogError(f"{rel}: Location target {t!r} leaves the project")
                            parts.pop()
                        elif part != ".":
                            parts.append(part)
                    queue.append(("/".join(parts), f"{rel}: Location target"))
    return entities, seen


def _is_option(spec: dict) -> bool:
    return str(spec.get("lifecycle") or "").lower() == "candidate"


def _is_role(spec: dict) -> bool:
    return str(spec.get("type") or "").lower() == "role"


def _rules(e: dict, me: str) -> dict:
    """The entity's `spec.morphogen`, checked: a mapping of known fields (project.MorphogenSpec)."""
    from pydantic import ValidationError
    from .project import MorphogenSpec
    raw = (e.get("spec") or {}).get("morphogen")
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        raise CatalogError(f"{e['_file']}: {me}: spec.morphogen is a mapping")
    try:
        MorphogenSpec.model_validate(raw)
    except ValidationError as err:
        raise CatalogError(f"{e['_file']}: {me}: spec.morphogen: " + "; ".join(
            f"{'.'.join(map(str, x['loc']))}: {x['msg']}" for x in err.errors())) from None
    return dict(raw)


def to_cells(entities: list[dict]) -> tuple[dict, dict, dict[str, str], dict]:
    """(cells, interfaces, the file each came from, the project's settings), in the cell format's dict form.
    The file of a cell is under its name, of an interface under `api:` and its name.
    The settings are what the one System that carries them says under `spec.morphogen`."""
    from .project import CELL_FIELDS
    cells: dict[str, dict] = {}
    interfaces: dict[str, dict] = {}
    origin: dict[str, str] = {}
    kinds: dict[str, str] = {}
    blocks: dict[str, dict] = {}   # a cell's own spec.morphogen, before the System's defaults
    settings: dict = {}
    settings_from: list[str] = []
    defaults: dict = {}
    for e in entities:
        kind = str(e["kind"]).lower()
        md, spec = e.get("metadata") or {}, e.get("spec") or {}
        ns = str(md.get("namespace") or "default").lower()
        me = ref_name(md["name"], kind, ns)
        if kind == "api":
            rules = _rules(e, me)
            extra = set(rules) - {"tests", "external"}
            if extra:
                raise CatalogError(f"{e['_file']}: {me}: on an API, spec.morphogen takes tests and external "
                                   f"(not {', '.join(sorted(extra))})")
            if me in interfaces:
                raise CatalogError(f"{me} is defined twice ({origin[f'api:{me}']}, {e['_file']})")
            interfaces[me] = {k: v for k, v in rules.items()}
            origin[f"api:{me}"] = e["_file"]
            continue
        if kind not in CELL_KINDS:
            continue
        if _is_option(spec) or _is_role(spec):   # an option for a role, or the role: never a cell
            continue
        rules = _rules(e, me)
        mine = {k: rules.pop(k) for k in SETTINGS if k in rules}
        carries = bool(mine)
        if mine:
            if kind != "system":
                raise CatalogError(f"{e['_file']}: {me}: {', '.join(mine)} are the project's settings: put them "
                                   "on the System entity")
            settings_from.append(f"{me} ({e['_file']})")
            defaults = mine.pop("defaults", {})
            settings = mine
        cell: dict = {}
        parent = {"component": spec.get("subcomponentOf") and ref_name(spec["subcomponentOf"], "component", ns)
                   or spec.get("system") and ref_name(spec["system"], "system", ns),
                   "system": spec.get("domain") and ref_name(spec["domain"], "domain", ns),
                   "domain": spec.get("subdomainOf") and ref_name(spec["subdomainOf"], "domain", ns),
                   "airesource": spec.get("system") and ref_name(spec["system"], "system", ns)}[kind]
        if parent:
            cell["in"] = parent
        if md.get("description"):
            cell["description"] = str(md["description"])
        if spec.get("owner"):
            cell["owner"] = parse_ref(str(spec["owner"]), "group", ns)
        if spec.get("lifecycle"):
            cell["lifecycle"] = str(spec["lifecycle"])
        prov = [ref_name(r, "api", ns) for r in spec.get("providesApis") or []]
        cons = [ref_name(r, "api", ns) for r in spec.get("consumesApis") or []]
        cons += [ref_name(r, "airesource" if kind == "airesource" else "component", ns) for r in spec.get("dependsOn") or []]
        if prov:
            cell["provides"] = prov
        if cons:
            cell["consumes"] = cons
        cell.update({k: v for k, v in rules.items() if k in CELL_FIELDS})
        if me in cells:
            raise CatalogError(f"{me} is defined twice, as a {kinds[me]} in {origin[me]} and as a {kind} in "
                               f"{e['_file']}: a cell is named by its name alone, so rename one")
        cells[me] = cell
        kinds[me] = kind
        origin[me] = e["_file"]
        if rules or ("morphogen" in spec and not carries):   # the System that only carries settings is no cell with rules
            blocks[me] = rules
    if len(settings_from) > 1:
        raise CatalogError("more than one System carries the project's settings: " + "; ".join(settings_from)
                           + ". Put trunk, sandbox, budget, autonomy and defaults on one System")
    # The System's defaults: cell fields every cell with rules of its own in that System inherits unless it sets its
    # own (a field set to null is its own: it opts out), the System itself too when it has rules of its own.
    holder = settings_from[0].split(" ")[0] if settings_from else None
    if defaults and holder:
        for name in blocks:
            at, seen = name, set()
            while at in cells and at not in seen:   # up the `in` chain to the enclosing System
                seen.add(at)
                if at == holder:
                    cells[name] = {**{k: v for k, v in defaults.items() if k not in blocks[name]}, **cells[name]}
                    break
                at = cells[at].get("in")
    # An interface named by a cell's name (a dependsOn, or a component listed as an API) is that cell;
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
            origin.setdefault(f"api:{i}", origin[name])
    return cells, interfaces, origin, settings
