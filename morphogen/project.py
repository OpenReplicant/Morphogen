"""The cell format: the project's cells and interfaces, read from its Backstage catalog.

The root is `catalog-info.yaml` at the repository root (a `Location` may name more files inside the
project). A cell's rules are `spec.morphogen` on the entity it judges:

    kind: Component
    metadata: {name: classify}
    spec:
      type: service
      lifecycle: experimental
      system: app                                  # the cell this one is in (`subcomponentOf` for a sub-grain cell)
      providesApis: [labels]
      morphogen:
        change: classify/classify.py#THRESHOLD in 0..100   # what may change; nothing else may
        run: python bench.py                               # the workload
        better: accuracy higher                            # the primary metric, and its direction
        tests: python -m unittest -q test_classify         # must pass on the candidate
        score: python score.py                             # optional: scores each run's output
    ---
    kind: API
    metadata: {name: labels}
    spec: {morphogen: {tests: python -m unittest -q contracts.test_labels}}

An entity with no `run` is structure, not a judged cell. The project's settings (trunk, sandbox,
sandbox_image, budget, autonomy) and `defaults` (cell fields every cell with rules in that System inherits
unless it sets its own) are `spec.morphogen` on the System; at most one System carries them. Options
(`spec.lifecycle: candidate`) and roles (`spec.type: role`) are never cells. See backstage.py.

**Default deny.** A candidate may change only the paths the judged cell's scope names in `change`.
Everything else is the judge's, every catalog file it reads included (the root and each Location
target): a candidate that changes, adds or removes one is refused before anything runs. A `change`
entry that names a setting (`path#NAME`, `path:dotted.key`) lets only that setting change in its file,
within its range or choices. `keep` names settings that must not change even in a file `change` opens.

Paths are relative to the project root; commands run in the cell's `dir` (default the root), and
interface tests from the root. The compiled form is what the judge already reads: a Structure, and
per cell a target spec. Held-out answers live in the uncommitted morphogen.local.yaml.
"""

from __future__ import annotations

import ast
import json
import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from . import documents
from .structure import Structure, StructureError

FILE = "catalog-info.yaml"   # the project's catalog root, at the repository root
LOCAL = "morphogen.local.yaml"
JUDGE_METRICS = ("wall_seconds", "cpu_seconds", "max_rss_kb")
METRIC_OPTIONS = {"min": "min_improvement", "max_regression": "max_regression", "gain": "gain",
                  "aggregate": "aggregate", "primary": "primary"}


class ProjectError(ValueError):
    pass


def _listed(v: Any) -> list:
    return [] if v is None else list(v) if isinstance(v, (list, tuple)) else [v]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class Rounds(_Strict):
    warmup: int | None = None
    repeats: int | None = None
    max_repeats: int | None = None


class SameAsBase(_Strict):
    gen: str
    run: str
    cases: int | None = None


class CellRules(_Strict):
    """A cell's rules: the fields of `spec.morphogen` on the entity it judges."""
    description: str | None = None
    dir: str = "."
    change: str | list[str] = []
    keep: str | list[str] = []
    run: str | None = None
    better: str | dict[str, Any] | None = None
    tests: str | list[str] = []
    score: str | None = None
    observe: str | dict[str, Any] | None = None
    same_as_base: SameAsBase | None = None
    same_output: bool | None = None
    guard: bool | dict[str, float] | None = None
    rounds: Rounds | None = None
    timeout: int | None = None
    simulates: str | None = None
    requires: list[str] = []


CELL_FIELDS = tuple(CellRules.model_fields)


class CellDoc(CellRules):
    """A cell as compiled: its rules, and what the catalog says around it."""
    in_: str | None = Field(None, alias="in")
    provides: str | list[str] = []
    consumes: str | list[str] = []
    owner: str | None = None        # who approves its candidates (a Backstage group or user ref)
    lifecycle: str | None = None    # experimental, production, ...: what `autonomy` keys on


class InterfaceDoc(_Strict):
    """An interface's tests: `spec.morphogen` on its API entity."""
    tests: str | list[str] = []
    external: Literal["consumes", "provides"] | None = None


class Budget(_Strict):
    model_config = ConfigDict(extra="allow")
    trials_per_day: int | None = None
    probes_per_day: int | None = None


class SystemRules(_Strict):
    """The project's settings and shared defaults: `spec.morphogen` on the System."""
    trunk: str | None = None
    sandbox: Literal["auto", "podman", "docker", "none"] | None = None
    sandbox_image: str | None = None
    budget: Budget | None = None
    autonomy: dict[str, Literal["merge", "review"]] | None = None   # lifecycle -> what a pass allows (default review)
    defaults: CellRules | None = None


class OptionRules(_Strict):
    """An option for a role: `spec.morphogen` on a Component with `spec.lifecycle: candidate`."""
    fills: str | list[str] | None = None
    parameters: dict[str, Any] | None = None
    licence: str | None = None
    docs: dict[str, Any] | None = None
    evaluation: dict[str, Any] | None = None


class MorphogenSpec(CellRules, InterfaceDoc, SystemRules, OptionRules):
    """Everything `spec.morphogen` may hold, flat: one entity may carry the fields of more than one."""


class ProjectDoc(BaseModel):
    cells: dict[str, CellDoc] = {}
    interfaces: dict[str, InterfaceDoc] = {}
    autonomy: dict[str, Literal["merge", "review"]] = {}


# --- the small grammars

def _safe_path(p: str, what: str) -> str:
    p = p.strip()
    pp = PurePosixPath(p)
    if not p or pp.is_absolute() or ".." in pp.parts:
        raise ProjectError(f"{what} {p!r}: give a path inside the project, relative to its root")
    return p


def parse_change(s: str) -> dict:
    """`path` or glob; `path#NAME` or `path:dotted.key`, optionally `in lo..hi` or `in [a, b]`."""
    if not isinstance(s, str) or not s.strip():
        raise ProjectError("an empty change entry")
    left, _, right = s.partition(" in ")
    left, right = left.strip(), right.strip()
    out: dict[str, Any] = {}
    if "#" in left:
        path, _, name = left.partition("#")
        if not name.isidentifier():
            raise ProjectError(f"change {s!r}: #{name} is not a Python name")
        out = {"path": _safe_path(path, "change"), "name": name}
    elif ":" in left:
        path, _, key = left.partition(":")
        if not key or any(not k for k in key.split(".")):
            raise ProjectError(f"change {s!r}: an empty key")
        out = {"path": _safe_path(path, "change"), "key": key}
    else:
        out = {"path": _safe_path(left, "change")}
    if right:
        if "name" not in out and "key" not in out:
            raise ProjectError(f"change {s!r}: only a setting (path#NAME or path:key) takes a range or choices")
        m = re.fullmatch(r"(-?[\d.]+(?:e-?\d+)?)\s*\.\.\s*(-?[\d.]+(?:e-?\d+)?)", right)
        if m:
            lo, hi = float(m.group(1)), float(m.group(2))
            if lo > hi:
                raise ProjectError(f"change {s!r}: the range runs from low to high")
            out["range"] = [lo, hi]
        elif right.startswith("["):
            choices = yaml.safe_load(right)
            if not isinstance(choices, list) or not choices:
                raise ProjectError(f"change {s!r}: choices are a list, e.g. [fast, slow]")
            out["choices"] = choices
        else:
            raise ProjectError(f"change {s!r}: after 'in', give lo..hi or [a, b]")
    return out


def parse_better(b: str | dict | None, scored: bool = False, observed: set[str] = frozenset()) -> dict:
    """`metric higher|lower[, metric higher|lower ...]`, or {metric: higher|lower|{higher: true, min: ...}}.
    The first is primary unless one says `primary: true`. A plain name is a judge metric (wall_seconds,
    cpu_seconds, max_rss_kb), else an observed one (from `observe`), else a scored one (from `score`)."""
    if b is None:
        return {}
    items: list[tuple[str, dict]] = []
    if isinstance(b, str):
        for part in (x.strip() for x in b.split(",")):
            words = part.split()
            if len(words) != 2 or words[1] not in ("higher", "lower"):
                raise ProjectError(f"better {part!r}: write 'metric higher' or 'metric lower'")
            items.append((words[0], {"direction": words[1]}))
    elif isinstance(b, dict):
        for name, v in b.items():
            if v in ("higher", "lower"):
                items.append((name, {"direction": v}))
                continue
            if not isinstance(v, dict) or sum(bool(v.get(d)) for d in ("higher", "lower")) != 1:
                raise ProjectError(f"better {name}: give higher or lower, e.g. {{higher: true, min: 0.05}}")
            m = {"direction": "higher" if v.get("higher") else "lower"}
            for k, x in v.items():
                if k in ("higher", "lower"):
                    continue
                if k not in METRIC_OPTIONS:
                    raise ProjectError(f"better {name}: unknown option {k!r} ({', '.join(METRIC_OPTIONS)})")
                m[METRIC_OPTIONS[k]] = x
            items.append((name, m))
    else:
        raise ProjectError("better: a string or a mapping")
    out: dict[str, dict] = {}
    explicit = any(m.get("primary") for _, m in items)
    for i, (name, m) in enumerate(items):
        if "." in name or name in JUDGE_METRICS:
            full = name
        elif name in observed or ("*" in observed and not scored):
            full = f"observed.{name}"
        elif scored:
            full = f"scored.{name}"
        else:
            raise ProjectError(f"better {name!r}: not a judge metric ({', '.join(JUDGE_METRICS)}); "
                               "score it with `score:` or collect it with `observe:`")
        m.setdefault("primary", (i == 0) if not explicit else False)
        out[full] = m
    return out


def _glob_re(pattern: str) -> re.Pattern:
    if pattern.endswith("/"):
        pattern += "**"
    out, i = "", 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out, i = out + "(?:.*/)?", i + 3
        elif pattern.startswith("**", i):
            out, i = out + ".*", i + 2
        elif c == "*":
            out, i = out + "[^/]*", i + 1
        elif c == "?":
            out, i = out + "[^/]", i + 1
        else:
            out, i = out + re.escape(c), i + 1
    return re.compile(out + r"\Z")


# --- settings: does a file differ from the base only in the named settings?

def _masked_python(text: str, names: set[str]) -> str:
    tree = ast.parse(text)
    for node in tree.body:
        targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, ast.AnnAssign) else []
        if any(isinstance(t, ast.Name) and t.id in names for t in targets):
            node.value = ast.Constant(None)
    return ast.dump(tree)


def _masked_data(text: str, suffix: str, keys: set[str]) -> str:
    data = tomllib.loads(text) if suffix == ".toml" else yaml.safe_load(text)
    for key in keys:
        d, parts = data, key.split(".")
        for p in parts[:-1]:
            d = d.get(p) if isinstance(d, dict) else None
        if isinstance(d, dict):
            d.pop(parts[-1], None)
    return json.dumps(data, sort_keys=True, default=str)


def only_settings_differ(base: Path, cand: Path, names: set[str], keys: set[str]) -> bool:
    try:
        b, c = base.read_text(), cand.read_text()
        if base.suffix == ".py":
            return _masked_python(b, names) == _masked_python(c, names)
        return _masked_data(b, base.suffix, keys) == _masked_data(c, cand.suffix, keys)
    except (OSError, SyntaxError, ValueError, yaml.YAMLError, tomllib.TOMLDecodeError):
        return False


# --- the project

def read_catalog(read_text, files: list[str] = (FILE,)) -> tuple[dict, dict, dict, dict, list[str]]:
    """The catalog at `files` (the root, and the Location targets it names) read through `read_text`:
    (cells, interfaces, where each came from, the project's settings, the files read)."""
    from . import backstage as bs
    try:
        entities, read = bs.read(list(files), read_text)
        cells, ifaces, origin, settings = bs.to_cells(entities)
    except bs.CatalogError as e:
        raise ProjectError(str(e)) from None
    return cells, ifaces, origin, settings, read


def git_reader(repo: Path, sha: str):
    """Reads project files as committed at `sha`, never the working copy."""
    import subprocess

    def read_text(rel: str) -> str:
        r = subprocess.run(["git", "show", f"{sha}:{rel}"], cwd=repo, capture_output=True, text=True)
        if r.returncode != 0:
            raise FileNotFoundError(2, "not in the commit", rel)
        return r.stdout
    return read_text


def settings_at(read_text) -> dict:
    """The project's settings (what the System's `spec.morphogen` says) through `read_text`, or {} when
    there is no catalog root."""
    try:
        read_text(FILE)
    except OSError:
        return {}
    return read_catalog(read_text)[3]


class Project:
    def __init__(self, doc: ProjectDoc, source: str = FILE, rule_files: list[str] = (),
                 sources: dict | None = None, settings: dict | None = None):
        self.doc, self.source = doc, source
        # Every catalog file the rules were read from (the root and each Location target): never changeable.
        self.rule_files = list(rule_files)
        self.sources = sources or {}
        self.settings = settings or {}
        self.changes = {n: [parse_change(x) for x in _listed(c.change)] for n, c in doc.cells.items()}
        self.keeps = {n: [parse_change(x) for x in _listed(c.keep)] for n, c in doc.cells.items()}
        for n, ks in self.keeps.items():
            for k in ks:
                if "name" not in k and "key" not in k or "range" in k or "choices" in k:
                    raise ProjectError(f"cell {n}: keep names a setting (path#NAME or path:key), without a range")
        for n, c in doc.cells.items():
            _safe_path(c.dir, f"cell {n}: dir")
        self._structure = self._compile_structure()

    @classmethod
    def from_parts(cls, cells: dict, interfaces: dict, origin: dict, settings: dict, files: list[str],
                   source: str = FILE) -> Project:
        try:
            doc = ProjectDoc.model_validate({"cells": cells, "interfaces": interfaces,
                                             "autonomy": settings.get("autonomy") or {}})
            return cls(doc, source, rule_files=files, sources=origin, settings=settings)
        except ValidationError as e:
            raise ProjectError(f"{source}: " + "; ".join(
                f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors())) from None

    @classmethod
    def load(cls, tree: Path, file: str = FILE) -> Project | None:
        """The project in `tree` (a checkout): its catalog read from `catalog-info.yaml` at the root (and
        the Location targets it names), or None when there is none."""
        tree = Path(tree)
        if not (tree / file).exists():
            return None
        from . import backstage as bs
        cells, ifaces, origin, settings, files = read_catalog(bs.fs_reader(tree), [file])
        return cls.from_parts(cells, ifaces, origin, settings, files, str(tree / file))

    # what the judge reads

    def _compile_structure(self) -> Structure:
        cells = {}
        for n, c in self.doc.cells.items():
            params = {}
            for ch in self.changes[n]:
                if "name" in ch or "key" in ch:
                    p = {"file": ch["path"], "owner": "agent",
                         **{k: ch[k] for k in ("name", "key", "range", "choices") if k in ch}}
                    params[ch.get("name") or ch["key"]] = p
            for k in self.keeps[n]:
                params[k.get("name") or k["key"]] = {"file": k["path"], "owner": "operator",
                                                     **{x: k[x] for x in ("name", "key") if x in k}}
            cells[n] = {"parent": c.in_, "provides": _listed(c.provides), "consumes": _listed(c.consumes),
                        "parameters": params, **({"measure": f"cell:{n}"} if c.run else {}),
                        **({"guard": c.guard} if c.guard is not None else {})}
        interfaces = {}
        for n, i in self.doc.interfaces.items():
            if isinstance(i, InterfaceDoc):
                interfaces[n] = {"tests": _listed(i.tests), **({"external": i.external} if i.external else {})}
            else:
                interfaces[n] = {"tests": _listed(i)}
        try:
            s = Structure.from_dict({"cells": cells, "interfaces": interfaces}, self.source)
            s.origins = dict(self.sources)
        except StructureError as e:
            raise ProjectError(str(e)) from None
        return s   # structural errors (gaps, cycles) are findings: `structure check` reports them

    def errors(self) -> list[str]:
        return [f.message if f.kind == "conflict" else f"{f.subject}: {f.message}"
                for f in self._structure.check() if f.severity == "error"]

    def resolve(self, name: str) -> str:
        """A cell's name as written: its key, or a Backstage ref in any spelling (classify,
        component:classify, component:default/classify)."""
        if name in self.doc.cells:
            return name
        from . import backstage as bs
        try:
            ref = bs.ref_name(name, "component")
        except bs.CatalogError:
            return name
        return ref if ref in self.doc.cells else name

    def gate(self, name: str, passed: bool) -> dict:
        """What a verdict on this cell allows, by this project's rules (the base's): `merge` when its
        lifecycle is one `autonomy` lets an agent merge, `review` (a person decides, the owner when
        one is named) otherwise, `none` without a pass. The judge never merges; this says who may."""
        c = self.cell(name)
        decision = (self.doc.autonomy.get(c.lifecycle or "", "review") if passed else "none")
        return {"decision": decision, "lifecycle": c.lifecycle, "owner": c.owner}

    def structure(self) -> Structure:
        return self._structure

    def cell(self, name: str) -> CellDoc:
        name = self.resolve(name)
        if name not in self.doc.cells:
            raise ProjectError(f"no cell {name!r} in the catalog ({FILE})")
        return self.doc.cells[name]

    def dir(self, name: str) -> Path:
        return Path(self.cell(name).dir)

    def spec(self, name: str, local: dict | None = None) -> dict:
        """The cell as a target spec (documents.Target), with held-out paths from `local`."""
        name = self.resolve(name)
        c, local = self.cell(name), local or {}
        if not c.run:
            raise ProjectError(f"cell {name!r} has no run: nothing to measure")
        observer = None
        if c.observe is not None:
            observer = {"type": "otel"} if c.observe == "otel" else dict(c.observe) if isinstance(c.observe, dict) \
                else {"run": c.observe, "collected": "outside"}
        observed = set((observer or {}).get("metrics", {}))
        if observer and observer.get("type", "command") == "command":
            observed |= {"*"}
        metrics = parse_better(c.better or "wall_seconds lower", scored=bool(c.score), observed=observed)
        measure: dict[str, Any] = {"run": c.run, "metrics": metrics,
                                   "same_output": c.same_output if c.same_output is not None else not c.score}
        if c.rounds:
            measure.update(c.rounds.model_dump(exclude_none=True))
        if c.score:
            measure["score"] = {"run": c.score, **{k: local[k] for k in ("private", "search") if local.get(k)}}
        if local.get("inputs"):
            measure["inputs"] = local["inputs"]
        if observer:
            measure["observer"] = observer
        spec: dict[str, Any] = {"name": name, "measure": measure}
        tests = _listed(c.tests)
        if tests:
            spec["check"] = " && ".join(f"( {t} )" if len(tests) > 1 else t for t in tests)
        if c.same_as_base:
            spec["equivalence"] = c.same_as_base.model_dump(exclude_none=True)
        if c.description:
            spec["description"] = c.description
        if c.simulates:
            spec.update(interface="simulated", simulates=c.simulates)
        if c.timeout:
            spec["timeout"] = c.timeout
        if c.requires:
            spec["requires"] = c.requires
        try:
            return documents.validate("target", spec, f"{FILE} cell {name}")
        except documents.DocumentError as e:
            raise ProjectError(str(e)) from None

    # default deny

    def _entries(self, cells) -> list[dict]:
        return [e for c in cells for e in self.changes.get(c, [])]

    def allows(self, cells, path: str) -> bool:
        if path in (FILE, LOCAL) or path in self.rule_files:   # the rules themselves never change: the catalog root and every file it names
            return False
        return any(_glob_re(e["path"]).match(path) for e in self._entries(cells))

    def check_changes(self, cells, changed: list[str], btree: Path, ctree: Path) -> list[str]:
        """What the candidate changed that the scope's `change` does not allow, one line each."""
        entries = self._entries(cells)
        bad = []
        for path in changed:
            if not self.allows(cells, path):
                bad.append(f"{path}: outside what the cell may change")
                continue
            c = ctree / path
            if c.is_symlink():
                bad.append(f"{path}: a symbolic link (candidates may not add or change links)")
                continue
            plain = [e for e in entries if "name" not in e and "key" not in e and _glob_re(e["path"]).match(path)]
            if plain:
                continue
            settings = [e for e in entries if e["path"] == path]
            names = {e["name"] for e in settings if "name" in e}
            keys = {e["key"] for e in settings if "key" in e}
            if not c.exists() or not only_settings_differ(btree / path, c, names, keys):
                bad.append(f"{path}: may change only in {', '.join(sorted(names | keys))}")
        return bad


def structure_file(root: Path, cfg: dict) -> str:
    """The file the structure is read from: the catalog root."""
    return FILE


def local_config(root: Path) -> dict:
    """morphogen.local.yaml at the root of the operator's checkout (never committed), or {}."""
    f = Path(root) / LOCAL
    if not f.exists():
        return {}
    data = yaml.safe_load(f.read_text()) or {}
    if not isinstance(data, dict):
        raise ProjectError(f"{LOCAL}: a mapping")
    return data
