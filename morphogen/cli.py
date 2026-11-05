"""Command line: morphogen structure check|scope|render FILE ..."""

from __future__ import annotations

import argparse
import json
import sys

from .render import mermaid
from .structure import Structure, StructureError, compare


def _structure(args) -> int:
    s = Structure.load(args.file)
    if args.action == "check":
        findings = s.check()
        out = {"findings": [f.__dict__ for f in findings], "coverage": s.coverage()}
        print(json.dumps(out, indent=2))
        return 1 if any(f.severity == "error" for f in findings) else 0
    if args.action == "scope":
        cells = sorted(s.scope(args.cell))
        print(json.dumps({"cell": args.cell, "scope": cells, "touched": s.touched(cells),
                          "boundary": s.boundary(cells), "tests": s.tests_for(cells),
                          "neighbours": s.neighbours(args.cell)}, indent=2))
        return 0
    if args.action == "render":
        overlay = compare(s, Structure.load(args.observed)) if args.observed else None
        sys.stdout.write(mermaid(s if not args.observed else _union(s, Structure.load(args.observed)), overlay))
        return 0
    return 2


def _union(intended: Structure, observed: Structure) -> Structure:
    """Both layers in one structure, so the overlay can mark what each lacks."""
    data = intended.doc.model_dump(exclude_none=True)
    obs = observed.doc.model_dump(exclude_none=True)
    for cid, cell in obs.get("cells", {}).items():
        mine = data.setdefault("cells", {}).setdefault(cid, {})
        for k, v in cell.items():
            if isinstance(v, list):
                mine[k] = sorted(set(mine.get(k, [])) | set(v))
            else:
                mine.setdefault(k, v)
    for iid, spec in obs.get("interfaces", {}).items():
        data.setdefault("interfaces", {}).setdefault(iid, spec)
    return Structure.from_dict(data, f"{intended.source} + {observed.source}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="morphogen")
    sub = ap.add_subparsers(dest="command", required=True)
    st = sub.add_parser("structure", help="check, scope or render a system structure")
    st.add_argument("action", choices=["check", "scope", "render"])
    st.add_argument("file")
    st.add_argument("cell", nargs="?", help="for scope: the cell whose scope to report")
    st.add_argument("--observed", help="for render: an observed structure to overlay")
    args = ap.parse_args(argv)
    try:
        if args.action == "scope" and not args.cell:
            ap.error("scope needs a cell")
        return _structure(args)
    except (StructureError, KeyError) as e:
        print(f"morphogen: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
