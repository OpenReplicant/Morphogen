"""The system structure: cells in a containment tree, interfaces as hyperedges between them.

Shaped like Milner's bigraphs: two structures over the same cells, a nesting forest (each cell has
at most one parent) and a hypergraph of connections (each interface joins the cells attached to
it, each as a provider or a consumer). Parameters sit on cells or interfaces.

The intended structure is authored as YAML and versioned in git; the observed structure is
generated in the same schema. `compare` lays one over the other.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

import yaml
from pydantic import BaseModel, ConfigDict, ValidationError, model_validator

# --- the document


class _Doc(BaseModel):
    model_config = ConfigDict(extra="allow")


class Parameter(_Doc):
    """A setting in a file. `name` is a module-level constant in a Python file; `key` is a dotted key
    in a YAML, JSON or TOML file. The owner decides who may change it: the agent within its range
    or choices; the operator or the judge, never in a candidate."""
    file: str
    name: str | None = None
    key: str | None = None
    owner: Literal["agent", "operator", "judge"]
    range: tuple[float, float] | None = None
    choices: list[Any] | None = None

    @model_validator(mode="after")
    def _check(self):
        if bool(self.name) == bool(self.key):
            raise ValueError("give exactly one of name (a Python constant) or key (a dotted key)")
        if self.range and self.range[0] > self.range[1]:
            raise ValueError("range must be [low, high]")
        return self


class Cell(_Doc):
    parent: str | None = None
    at: str | None = None              # a path, path#symbol, path:key, or an address in another format
    modality: str | None = None        # text | code | numeric | workflow | alternatives | ...
    provides: list[str] = []
    consumes: list[str] = []
    parameters: dict[str, Parameter] = {}
    measure: str | None = None
    cases: dict[str, str] = {}
    alternatives: str | None = None
    # When this cell is judged, its topmost ancestor with a `measure` (the system) is measured too, as a
    # constraint: the system's primary metric may not regress beyond `max_regression` (default 0.05).
    # `guard: false` turns it off for this cell.
    guard: bool | dict[str, float] | None = None


class Interface(_Doc):
    tests: list[str] = []
    parameters: dict[str, Parameter] = {}
    # The world outside the structure takes the other role: "consumes" for something the system
    # offers (an API, the whole system's behaviour), "provides" for something it relies on (a
    # model API, a database it does not own).
    external: Literal["consumes", "provides"] | None = None


class Document(_Doc):
    cells: dict[str, Cell] = {}
    interfaces: dict[str, Interface] = {}


class StructureError(ValueError):
    def __init__(self, source: str, problems: list[str]):
        self.source, self.problems = source, problems
        super().__init__(f"{source}: " + "; ".join(problems))


# --- findings


@dataclass(frozen=True)
class Finding:
    severity: Literal["error", "warning"]
    kind: str            # cycle | unknown-parent | unknown-interface | gap | conflict | unused | unattached | untested
    subject: str
    message: str


# --- the graph


@dataclass
class Structure:
    doc: Document
    source: str = "<data>"
    _children: dict[str, list[str]] = field(default_factory=dict, repr=False)
    # Where each cell and interface came from (morphogen.yaml, a Backstage catalog file, or both), and
    # where those sources disagree: set when the structure is compiled from the cell format.
    origins: dict[str, str] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)

    def __post_init__(self):
        self._children = {c: [] for c in self.doc.cells}
        for cid, cell in self.doc.cells.items():
            if cell.parent in self._children:
                self._children[cell.parent].append(cid)
        for kids in self._children.values():
            kids.sort()

    # loading

    @classmethod
    def from_dict(cls, data: Any, source: str = "<data>") -> Structure:
        try:
            doc = Document.model_validate({} if data is None else data)
        except ValidationError as e:
            raise StructureError(source, [f"{'.'.join(map(str, err['loc'])) or '(top)'}: {err['msg']}"
                                          for err in e.errors()]) from None
        return cls(doc, source)

    @classmethod
    def load(cls, path: str | Path) -> Structure:
        path = Path(path)
        try:
            data = yaml.safe_load(path.read_text())
        except OSError as e:
            raise StructureError(str(path), [f"cannot read: {e.strerror or e}"]) from None
        except yaml.YAMLError as e:
            raise StructureError(str(path), [f"not valid YAML: {e}"]) from None
        from .project import Project, ProjectError   # files are in the cell format; it compiles to this
        if not isinstance(data, dict) or not ("cells" in data or data.get("backstage")):
            raise StructureError(str(path), ["no cells: a structure file is in the cell format (morphogen.yaml)"])
        try:
            return Project.from_dict(data, str(path), root=path.parent).structure()
        except ProjectError as e:
            raise StructureError(str(path), [str(e)]) from None

    # containment

    @property
    def cells(self) -> dict[str, Cell]:
        return self.doc.cells

    @property
    def interfaces(self) -> dict[str, Interface]:
        return self.doc.interfaces

    def parent(self, cell: str) -> str | None:
        return self.cells[cell].parent

    def children(self, cell: str) -> list[str]:
        return list(self._children.get(cell, []))

    def roots(self) -> list[str]:
        return sorted(c for c, cell in self.cells.items() if cell.parent is None)

    def scope(self, cell: str) -> set[str]:
        """The cell and everything nested inside it."""
        self._known(cell)
        out, stack = set(), [cell]
        while stack:
            c = stack.pop()
            if c in out:
                continue
            out.add(c)
            stack.extend(self._children.get(c, []))
        return out

    # connection

    def providers(self, interface: str) -> list[str]:
        return sorted(c for c, cell in self.cells.items() if interface in cell.provides)

    def consumers(self, interface: str) -> list[str]:
        return sorted(c for c, cell in self.cells.items() if interface in cell.consumes)

    def attached(self, interface: str) -> set[str]:
        return set(self.providers(interface)) | set(self.consumers(interface))

    def touched(self, cells: Iterable[str]) -> list[str]:
        """Interfaces any of these cells provides or consumes."""
        cells = set(cells)
        return sorted({i for c in cells for i in (*self.cells[c].provides, *self.cells[c].consumes)})

    def boundary(self, cells: Iterable[str]) -> list[str]:
        """Interfaces joining something inside to something outside: attached to a cell outside the
        scope, or open to the world beyond the structure (`external`)."""
        cells = set(cells)
        out = []
        for i in self.touched(cells):
            outside = self.attached(i) - cells
            spec = self.interfaces.get(i)
            if outside or (spec is not None and spec.external):
                out.append(i)
        return out

    def tests_for(self, cells: Iterable[str]) -> list[str]:
        """What a change inside these cells must pass: the tests of every interface they touch,
        internal and boundary, in a stable order without repeats."""
        seen, out = set(), []
        for i in self.touched(cells):
            for t in (self.interfaces[i].tests if i in self.interfaces else []):
                if t not in seen:
                    seen.add(t)
                    out.append(t)
        return out

    def ancestors(self, cell: str) -> list[str]:
        """The cells enclosing this one, innermost first."""
        self._known(cell)
        out, c = [], self.cells[cell].parent
        while c is not None and c in self.cells and c not in out:
            out.append(c)
            c = self.cells[c].parent
        return out

    def gate_interfaces(self, cell: str) -> list[str]:
        """The interfaces a change inside this cell must keep: every one its scope touches, and every
        one at the boundary of each system enclosing it (what that system promises or relies on: a
        change inside it can break those though the cell touches neither)."""
        out = list(self.touched(self.scope(cell)))
        for a in self.ancestors(cell):
            out += [i for i in self.boundary(self.scope(a)) if i not in out]
        return out

    def tests_for_cell(self, cell: str) -> list[str]:
        """The tests the judge runs for a change inside this cell (its gate's interfaces)."""
        seen, out = set(), []
        for i in self.gate_interfaces(cell):
            for t in (self.interfaces[i].tests if i in self.interfaces else []):
                if t not in seen:
                    seen.add(t)
                    out.append(t)
        return out

    def neighbours(self, cell: str) -> list[str]:
        """Cells sharing an interface with this one."""
        self._known(cell)
        return sorted({c for i in self.touched([cell]) for c in self.attached(i)} - {cell})

    # checks

    def check(self) -> list[Finding]:
        f: list[Finding] = [Finding("error", "conflict", c.split(":", 1)[0], c) for c in self.conflicts]
        for cid, cell in self.cells.items():
            if cell.parent is not None and cell.parent not in self.cells:
                f.append(Finding("error", "unknown-parent", cid, f"parent {cell.parent!r} is not a cell"))
        for cid in self.cells:
            seen, c = set(), cid
            while c is not None and c in self.cells:
                if c in seen:
                    f.append(Finding("error", "cycle", cid, "containment loops back on itself"))
                    break
                seen.add(c)
                c = self.cells[c].parent
        used = set()
        for cid, cell in self.cells.items():
            for i in (*cell.provides, *cell.consumes):
                used.add(i)
                if i not in self.interfaces:
                    f.append(Finding("error", "unknown-interface", cid, f"attaches to undeclared interface {i!r}"))
        for i, spec in self.interfaces.items():
            prov, cons = self.providers(i), self.consumers(i)
            if not prov and not cons:
                f.append(Finding("warning", "unattached", i, "no cell provides or consumes it"))
                continue
            if not prov and spec.external != "provides":
                f.append(Finding("error", "gap", i, f"consumed by {', '.join(cons)} but nothing provides it"))
            if not cons and spec.external != "consumes":
                f.append(Finding("warning", "unused", i, f"provided by {', '.join(prov)} but nothing consumes it"))
            if not spec.tests:
                f.append(Finding("warning", "untested", i, "no tests: what it promises is not enforced"))
        return sorted(f, key=lambda x: (x.severity != "error", x.kind, x.subject))

    def coverage(self) -> dict:
        """Intent coverage: interfaces whose promises are backed by tests."""
        tested = [i for i, s in self.interfaces.items() if s.tests]
        n = len(self.interfaces)
        return {"interfaces": n, "tested": len(tested), "share": round(len(tested) / n, 3) if n else None,
                "untested": sorted(set(self.interfaces) - set(tested))}

    def _known(self, cell: str) -> None:
        if cell not in self.cells:
            raise KeyError(f"unknown cell {cell!r}")


# --- intended against observed


Status = Literal["convergence", "absence", "divergence"]


def compare(intended: Structure, observed: Structure) -> dict[str, dict[str, Status]]:
    """For each cell, interface and attachment: in both (convergence), only intended (absence), or
    only observed (divergence)."""

    def attachments(s: Structure) -> set[str]:
        return {f"{c} provides {i}" for c, cell in s.cells.items() for i in cell.provides} | \
               {f"{c} consumes {i}" for c, cell in s.cells.items() for i in cell.consumes}

    def contained(s: Structure) -> set[str]:
        return {f"{c} in {cell.parent}" for c, cell in s.cells.items() if cell.parent}

    def classify(a: set[str], b: set[str]) -> dict[str, Status]:
        return {k: ("convergence" if k in a and k in b else "absence" if k in a else "divergence")
                for k in sorted(a | b)}

    return {
        "cells": classify(set(intended.cells), set(observed.cells)),
        "interfaces": classify(set(intended.interfaces), set(observed.interfaces)),
        "attachments": classify(attachments(intended), attachments(observed)),
        "containment": classify(contained(intended), contained(observed)),
    }
