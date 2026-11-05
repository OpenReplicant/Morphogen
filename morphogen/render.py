"""Render a structure as a Mermaid flowchart: cells as nested boxes, interfaces as edges.

An interface joining one provider and one consumer is drawn as an edge from provider to consumer;
one joining more, or open to the outside world, as a small hub. With a comparison overlay, parts
only intended are dashed (absences) and parts only observed are marked (divergences). `notes`
adds text to an element's label, for traffic from traces or a cell's latest verdict.
"""

from __future__ import annotations

import re

from .structure import Status, Structure

OUTSIDE = "outside"


def _id(kind: str, name: str) -> str:
    return f"{kind}_{re.sub(r'[^0-9A-Za-z_]', '_', name)}"


def _label(text: str) -> str:
    return text.replace('"', "'")


def mermaid(s: Structure, overlay: dict[str, dict[str, Status]] | None = None,
            notes: dict[str, str] | None = None) -> str:
    overlay, notes = overlay or {}, notes or {}
    cell_status = overlay.get("cells", {})
    if_status = overlay.get("interfaces", {})
    lines = ["flowchart LR"]
    styled: dict[str, list[str]] = {"absence": [], "divergence": []}

    def label(name: str) -> str:
        extra = notes.get(name)
        return _label(f"{name}<br/><small>{extra}</small>" if extra else name)

    def emit(cell: str, depth: int) -> None:
        pad = "  " * depth
        kids = s.children(cell)
        cid = _id("c", cell)
        if kids:
            lines.append(f'{pad}subgraph {cid}["{label(cell)}"]')
            for k in kids:
                emit(k, depth + 1)
            lines.append(f"{pad}end")
        else:
            lines.append(f'{pad}{cid}["{label(cell)}"]')
        st = cell_status.get(cell)
        if st in styled:
            styled[st].append(cid)

    for r in s.roots():
        emit(r, 1)
    # cells whose parent is unknown are still drawn
    drawn = set()
    for r in s.roots():
        drawn |= s.scope(r)
    for c in sorted(set(s.cells) - drawn):
        emit(c, 1)

    external = any(spec.external for spec in s.interfaces.values())
    if external:
        lines.append(f'  {OUTSIDE}(["outside"])')

    att_status = overlay.get("attachments", {})

    def edge_status(name: str, provider: str | None, consumer: str | None) -> str | None:
        found = [att_status.get(f"{provider} provides {name}") if provider else None,
                 att_status.get(f"{consumer} consumes {name}") if consumer else None,
                 if_status.get(name)]
        for st in ("absence", "divergence"):
            if st in found:
                return st
        return None

    def node(c: str | None) -> str:
        return OUTSIDE if c is None else _id("c", c)

    edge_index = 0
    dashed, marked = [], []

    def edge(src: str, dst: str, text: str | None, st: str | None) -> None:
        nonlocal edge_index
        lines.append(f'  {src} -->|"{text}"| {dst}' if text else f"  {src} --> {dst}")
        if st == "absence":
            dashed.append(edge_index)
        elif st == "divergence":
            marked.append(edge_index)
        edge_index += 1

    for name, spec in sorted(s.interfaces.items()):
        prov: list[str | None] = list(s.providers(name))
        cons: list[str | None] = list(s.consumers(name))
        if spec.external == "consumes":
            cons.append(None)
        elif spec.external == "provides":
            prov.append(None)
        text = label(name)
        if len(prov) == 1 and len(cons) == 1:
            edge(node(prov[0]), node(cons[0]), text, edge_status(name, prov[0], cons[0]))
        elif prov or cons:
            hub = _id("i", name)
            lines.append(f'  {hub}(("{text}"))')
            for p in prov:
                edge(node(p), hub, None, edge_status(name, p, None))
            for c in cons:
                edge(hub, node(c), None, edge_status(name, None, c))
            st = if_status.get(name)
            if st in styled:
                styled[st].append(hub)

    lines.append("  classDef absence stroke-dasharray: 5 5,opacity:0.6")
    lines.append("  classDef divergence stroke:#d33,stroke-width:2px")
    for st, ids in styled.items():
        if ids:
            lines.append(f"  class {','.join(ids)} {st}")
    if dashed:
        lines.append(f"  linkStyle {','.join(map(str, dashed))} stroke-dasharray: 5 5")
    if marked:
        lines.append(f"  linkStyle {','.join(map(str, marked))} stroke:#d33,stroke-width:2px")
    return "\n".join(lines) + "\n"
