"""Morphogen's MCP server: the tools an agent harness uses, and the judge it cannot edit.

The agent may read the structure, measure, probe, judge, tune, and add its own notes to the evidence
log (as stated or inferred). Only the judge, running here, writes measured evidence.
"""

from __future__ import annotations

import functools
import os
from pathlib import Path

from mcp.server.mcpserver import MCPServer

from . import judge as judge_mod
from .documents import DocumentError, load_config
from .evidence import Evidence
from .optimize import catalog, make, prior_from_evidence
from .optimize import tune as tune_mod
from .render import mermaid
from .project import structure_file
from .structure import Structure, StructureError

server = MCPServer(
    name="morphogen",
    instructions=(
        "Morphogen improves a system at any scope behind a judge the agent cannot edit. morphogen.yaml "
        "says what the cells are, which interfaces join them, which tests guard each, and what each cell "
        "may change (`change`); nothing else may change, and a candidate that touches anything else is "
        "refused. To improve a cell: measure it (target cell:NAME), change it on a branch, commit, then "
        "call judge(target, candidate); or call tune(target) to search its bounded settings. probe gives "
        "practice feedback, never a verdict. Merging is the operator's decision."
    ),
)


def project_root() -> Path:
    """The project the server works on: MORPHOGEN_PROJECT, Claude Code's project dir, or cwd."""
    p = os.environ.get("MORPHOGEN_PROJECT") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    return judge_mod.repo_root(Path(p).resolve())


def _ctx():
    root = project_root()
    return root, load_config(root)


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (judge_mod.JudgeError, StructureError, DocumentError, ValueError, LookupError, RuntimeError) as e:
            return {"error": str(e)}
    return wrapper


def _structure(file: str | None) -> Structure:
    root, cfg = _ctx()
    return Structure.load(root / (file or structure_file(root, cfg)))


def _target(target: str) -> tuple[str, str | None]:
    """Passed through: the judge resolves cell:NAME, a cell's name or its dir on the base commit."""
    return target, None


@server.tool()
@_safe
def structure_check(file: str | None = None) -> dict:
    """Check the system structure (default: morphogen.yaml): cycles, unknown
    parents or interfaces, gaps, unused or untested interfaces; and intent coverage."""
    s = _structure(file)
    return {"findings": [f.__dict__ for f in s.check()], "coverage": s.coverage(), "roots": s.roots(),
            "sources": s.origins}


@server.tool()
@_safe
def structure_scope(cell: str, file: str | None = None) -> dict:
    """A cell's scope (it and everything inside it): the interfaces it touches, its boundary, the tests
    any change inside it must pass, and its neighbours."""
    s = _structure(file)
    cells = sorted(s.scope(cell))
    return {"cell": cell, "scope": cells, "touched": s.touched(cells), "boundary": s.boundary(cells),
            "tests": s.tests_for(cells), "neighbours": s.neighbours(cell)}


@server.tool()
@_safe
def structure_render(file: str | None = None) -> dict:
    """The structure as a Mermaid flowchart: cells as nested boxes, interfaces as edges or hubs."""
    return {"mermaid": mermaid(_structure(file))}


@server.tool()
@_safe
def measure(target: str, ref: str = "main") -> dict:
    """Measure a cell (cell:NAME, its name, or its dir) at a commit; recorded as evidence."""
    root, cfg = _ctx()
    return judge_mod.measure(root, cfg, _target(target)[0], ref, Evidence.for_project(root))


@server.tool()
@_safe
def probe(target: str, candidate: str, base: str | None = None, cases: int = 5, rounds: int = 3) -> dict:
    """Practice feedback on a candidate under the judge's rules: check output, wrong cases, metric
    estimates. Never a verdict, and it cannot be proposed for merging."""
    root, cfg = _ctx()
    tgt, cell = _target(target)
    return judge_mod.probe(root, cfg, tgt, candidate, Evidence.for_project(root), base, cases, rounds, cell=cell)


@server.tool()
@_safe
def judge(target: str, candidate: str, base: str = "main", labels: dict | None = None) -> dict:
    """Score a candidate commit against the base by the base's rules (its morphogen.yaml; default deny).
    With target `cell:NAME`, the candidate must also pass the tests of every interface the cell's scope
    touches, from the base's structure. The verdict is measured evidence. `labels` (optimizer,
    approach) are recorded, never decide."""
    root, cfg = _ctx()
    tgt, cell = _target(target)
    return judge_mod.judge(root, cfg, tgt, base, candidate, Evidence.for_project(root), labels, cell=cell)


@server.tool()
@_safe
def tune(target: str, optimizer: str = "selector", steps: int = 5, trials: int = 20, rounds: int = 2,
         base: str = "main", seed: int | None = None) -> dict:
    """Search the cell's bounded settings (`change` entries with a range or choices): probe each proposal
    on a branch, then judge the best. optimizer: a name from optimizers_list; the default, selector,
    chooses among the available ones (a bandit on probe gains, primed by earlier verdicts)."""
    root, cfg = _ctx()
    (tgt, cell), ev = _target(target), Evidence.for_project(root)
    options = {"trials": trials, "seed": seed, "steps": steps}
    if optimizer == "selector":
        options["prior"] = prior_from_evidence(ev, tgt)
    return tune_mod(root, cfg, tgt, make(optimizer, **options), ev, base=base, rounds=rounds,
                    max_trials=trials, cell=cell)


@server.tool()
@_safe
def optimizers_list() -> list:
    """The optimizer catalog: built-in, adapters (available when installed), the selector, and planned
    entries, each with the modalities it handles and what it needs."""
    return catalog()


@server.tool()
@_safe
def evidence_query(contains: str | None = None, by: str | None = None, limit: int = 20) -> list | dict:
    """Evidence records, newest first: verdicts, probes and measurements by the judge, notes by agents."""
    root, _ = _ctx()
    return Evidence.for_project(root).query(contains=contains, by=by, limit=limit)


@server.tool()
@_safe
def evidence_note(claim: str, source: str | None = None, trust: str = "inferred",
                  supports: list[int] | None = None, challenges: list[int] | None = None) -> dict:
    """Add the agent's own claim: trust `stated` (from a source, which you must give) or `inferred`
    (reasoned). It may cite records it supports or challenges. Only the judge writes measured evidence."""
    if trust not in ("stated", "inferred"):
        raise ValueError("an agent's note is 'stated' or 'inferred'; only the judge writes measured evidence")
    if trust == "stated" and not source:
        raise ValueError("a stated claim needs its source")
    root, _ = _ctx()
    rec = {"claim": claim, "trust": trust, "by": "agent", "kind": "note"}
    if source:
        rec["source"] = source
    if supports:
        rec["supports"] = supports
    if challenges:
        rec["challenges"] = challenges
    return Evidence.for_project(root).append(rec)


@server.tool()
@_safe
def evidence_verify() -> dict:
    """Check the evidence log's hash chain: intact, or the first record that was changed."""
    root, _ = _ctx()
    ev = Evidence.for_project(root)
    ok, at = ev.verify()
    return {"chain": "intact" if ok else f"broken at record {at}", "records": len(ev.dump()), "path": str(ev.path)}


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
