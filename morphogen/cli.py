"""Command line.

    morphogen status
    morphogen structure check|scope|render FILE [CELL] [--observed FILE]
    morphogen measure TARGET [--ref main]
    morphogen judge TARGET CANDIDATE [--base main]
    morphogen tune TARGET [--optimizer NAME] [--steps N] [--trials N]
    morphogen optimizers
    morphogen evidence [--verify] [--limit N] [--by judge]
    morphogen ui [--host 127.0.0.1] [--port 8765]

TARGET is `cell:NAME` for a cell with a `run` in morphogen.yaml (or the cell's name, or its `dir`).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import judge as judge_mod
from .documents import DocumentError, load_config
from .evidence import Evidence
from .optimize import CATALOG, catalog, make, prior_from_evidence, tune
from .render import mermaid
from .project import ProjectError
from .structure import Structure, StructureError, compare


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, default=str))


def _root() -> Path:
    return judge_mod.repo_root(Path.cwd())


def _target(root: Path, cfg: dict, target: str) -> tuple[str, str | None]:
    """A target is passed through: the judge resolves cell:NAME, a cell's name or its dir on the base."""
    return target, None


def _union(intended: Structure, observed: Structure) -> Structure:
    """Both layers in one structure, so the overlay can mark what each lacks."""
    data = intended.doc.model_dump(exclude_none=True)
    for cid, cell in observed.doc.model_dump(exclude_none=True).get("cells", {}).items():
        mine = data.setdefault("cells", {}).setdefault(cid, {})
        for k, v in cell.items():
            mine[k] = sorted(set(mine.get(k, [])) | set(v)) if isinstance(v, list) else mine.get(k, v)
    for iid, spec in observed.doc.model_dump(exclude_none=True).get("interfaces", {}).items():
        data.setdefault("interfaces", {}).setdefault(iid, spec)
    return Structure.from_dict(data, f"{intended.source} + {observed.source}")


def cmd_status(a) -> int:
    from .status import status
    start = Path.cwd()
    try:
        root = _root()
    except judge_mod.JudgeError:
        _print(status(start))
        return 0
    _print(status(root, load_config(root), Evidence.for_project(root)))
    return 0


def cmd_structure(a) -> int:
    s = Structure.load(a.file)
    if a.action == "check":
        findings = s.check()
        _print({"findings": [f.__dict__ for f in findings], "coverage": s.coverage(), "sources": s.origins})
        return 1 if any(f.severity == "error" for f in findings) else 0
    if a.action == "scope":
        if not a.cell:
            raise KeyError("scope needs a cell")
        cells = sorted(s.scope(a.cell))
        _print({"cell": a.cell, "scope": cells, "touched": s.touched(cells), "boundary": s.boundary(cells),
                "tests": s.tests_for(cells), "neighbours": s.neighbours(a.cell)})
        return 0
    if a.observed:
        o = Structure.load(a.observed)
        sys.stdout.write(mermaid(_union(s, o), compare(s, o)))
    else:
        sys.stdout.write(mermaid(s))
    return 0


def cmd_measure(a) -> int:
    root = _root()
    cfg = load_config(root)
    target, _ = _target(root, cfg, a.target)
    _print(judge_mod.measure(root, cfg, target, a.ref, Evidence.for_project(root)))
    return 0


def cmd_judge(a) -> int:
    root = _root()
    cfg = load_config(root)
    target, cell = _target(root, cfg, a.target)
    r = judge_mod.judge(root, cfg, target, a.base, a.candidate, Evidence.for_project(root), cell=cell)
    _print(r)
    return 0 if r["verdict"] == "pass" else 1


def cmd_tune(a) -> int:
    root = _root()
    cfg = load_config(root)
    (target, cell), ev = _target(root, cfg, a.target), Evidence.for_project(root)
    options = {"trials": a.trials, "seed": a.seed, "steps": a.steps}
    if a.optimizer == "selector":
        options["prior"] = prior_from_evidence(ev, target)
    opt = make(a.optimizer, **options)
    r = tune(root, cfg, target, opt, ev, base=a.base, rounds=a.rounds, max_trials=a.trials, cell=cell)
    _print(r)
    return 0 if r.get("verdict") == "pass" else 1


def cmd_optimizers(a) -> int:
    _print(catalog())
    return 0


def cmd_evidence(a) -> int:
    ev = Evidence.for_project(_root())
    if a.verify:
        ok, at = ev.verify()
        _print({"chain": "intact" if ok else f"broken at record {at}", "records": len(ev.dump()),
                "path": str(ev.path)})
        return 0 if ok else 1
    _print(ev.query(by=a.by, limit=a.limit))
    return 0


def cmd_ui(a) -> int:
    from .ui import serve
    httpd = serve(_root(), a.host, a.port)
    host, port = httpd.server_address[:2]
    print(f"Morphogen UI on http://{host}:{port}/ (read-only; Ctrl-C to stop)", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="morphogen", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)

    sa = sub.add_parser("status", help="where the project stands: sources, cells on the trunk, what is missing, the next step")
    sa.set_defaults(fn=cmd_status)

    st = sub.add_parser("structure", help="check, scope or render a system structure")
    st.add_argument("action", choices=["check", "scope", "render"])
    st.add_argument("file")
    st.add_argument("cell", nargs="?", help="for scope: the cell whose scope to report")
    st.add_argument("--observed", help="for render: an observed structure to overlay")
    st.set_defaults(fn=cmd_structure)

    me = sub.add_parser("measure", help="measure a target at a commit")
    me.add_argument("target")
    me.add_argument("--ref", default="main")
    me.set_defaults(fn=cmd_measure)

    ju = sub.add_parser("judge", help="score a candidate commit against a base, by the base's rules")
    ju.add_argument("target")
    ju.add_argument("candidate")
    ju.add_argument("--base", default="main")
    ju.set_defaults(fn=cmd_judge)

    tu = sub.add_parser("tune", help="search a cell's bounded settings; judge the best")
    tu.add_argument("target")
    tu.add_argument("--optimizer", choices=sorted(CATALOG), default="selector",
                    help="from the catalog (morphogen optimizers); default: selector, which chooses among the others")
    tu.add_argument("--steps", type=int, default=5, help="grid: values per numeric range")
    tu.add_argument("--trials", type=int, default=20, help="most proposals to try")
    tu.add_argument("--seed", type=int, default=None, help="random: the seed")
    tu.add_argument("--rounds", type=int, default=2, help="probe rounds per proposal")
    tu.add_argument("--base", default="main")
    tu.set_defaults(fn=cmd_tune)

    op = sub.add_parser("optimizers", help="list the optimizer catalog")
    op.set_defaults(fn=cmd_optimizers)

    ev = sub.add_parser("evidence", help="read or verify the evidence log")
    ev.add_argument("--verify", action="store_true")
    ev.add_argument("--limit", type=int, default=20)
    ev.add_argument("--by")
    ev.set_defaults(fn=cmd_evidence)

    ui = sub.add_parser("ui", help="serve the read-only web UI on localhost")
    ui.add_argument("--host", default="127.0.0.1")
    ui.add_argument("--port", type=int, default=8765)
    ui.set_defaults(fn=cmd_ui)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except (StructureError, DocumentError, ProjectError, judge_mod.JudgeError, KeyError, LookupError) as e:
        print(f"morphogen: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
