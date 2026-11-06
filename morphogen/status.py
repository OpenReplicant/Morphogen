"""Where a project stands, and the next step: what `morphogen status` reports.

It reads; it never writes. The judge reads the rules from the base commit (the trunk, `main` by
default), so status compares the trunk with the working tree: a cell counts once it is on the trunk.
Each cell on the trunk is checked with the judge's own checks, so status and the judge agree on what
is ready. The next step follows the map skill's order: one cell first, measured, then improved.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from . import judge as judge_mod
from .project import FILE, LOCAL, Project, ProjectError

CATALOG_NAMES = ("catalog-info.yaml", "catalog-info.yml")


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=False)


def _catalogs(repo: Path) -> list[str]:
    """Backstage catalog files in the checkout, tracked or not (ignored files excluded)."""
    p = _git(repo, "ls-files", "--cached", "--others", "--exclude-standard")
    files = p.stdout.splitlines() if p.returncode == 0 else []
    return sorted(f for f in files if Path(f).name in CATALOG_NAMES)


def _named_catalogs(tree: Path) -> list[str]:
    f = tree / FILE
    try:
        data = yaml.safe_load(f.read_text()) if f.exists() else None
    except yaml.YAMLError:
        return []
    b = (data or {}).get("backstage") if isinstance(data, dict) else None
    return [b] if isinstance(b, str) else list(b or [])


def _load(tree: Path) -> tuple[Project | None, str | None]:
    """The project on `tree`, or None; and a problem that stops it loading."""
    try:
        return Project.load(tree), None
    except (ProjectError, yaml.YAMLError) as e:
        return None, str(e)


def _cell_report(proj: Project, name: str, local: dict) -> dict:
    c = proj.doc.cells[name]
    out: dict = {"cell": name, "source": proj.sources.get(name, FILE)}
    if not c.run:
        out["ready"] = False
        out["role"] = "container" if any(proj.resolve(x.in_ or "") == name for x in proj.doc.cells.values()) else "part"
        return out
    problems, notes = [], []
    lc = next((v for k, v in (local.get("cells") or {}).items() if proj.resolve(k) == name), None)
    try:
        spec = proj.spec(name, lc)
        judge_mod._check_spec(spec)
    except (ProjectError, judge_mod.JudgeError) as e:
        problems.append(str(e))
    has_children = any(proj.resolve(x.in_ or "") == name for x in proj.doc.cells.values() if x.in_)
    if not proj.changes[name]:
        if has_children:
            notes.append("no `change` of its own: it is the system its cells' changes are guarded against")
        else:
            problems.append("no `change`: nothing in it may change, so no candidate can pass")
    if not c.better:
        notes.append("no `better`: judged on wall_seconds lower")
    if not proj.structure().tests_for(sorted(proj.structure().scope(name))) and not c.tests:
        notes.append("no tests: nothing says what it must keep doing")
    if c.score and not (lc or {}).get("private"):
        notes.append(f"its scorer has no held-out answers named in {LOCAL} (cells: {{{name}: {{private: PATH}}}})")
    out.update(ready=not problems, change=list(c.change) if isinstance(c.change, list) else [c.change] if c.change else [])
    if problems:
        out["problems"] = problems
    if notes:
        out["notes"] = notes
    return out


def _history(evidence, name: str) -> dict:
    counts = {"measurements": 0, "verdicts": 0, "passes": 0}
    for r in evidence.dump():
        subj = r.get("subject") or {}
        if r.get("by") != "judge" or name not in (subj.get("system"), (subj.get("path") or "").removeprefix("cell:")):
            continue
        if r.get("kind") == "measurement":
            counts["measurements"] += 1
        elif r.get("kind") == "verdict":
            counts["verdicts"] += 1
            counts["passes"] += r.get("verdict") == "pass"
    return counts


def status(start: Path, cfg: dict | None = None, evidence=None) -> dict:
    """The project's sources, its cells on the trunk and in the working tree, what is missing, and
    the next step. `cfg` is load_config's result; `evidence` the project's log."""
    start = Path(start)
    out: dict = {"project": str(start)}
    p = _git(start, "rev-parse", "--show-toplevel")
    if p.returncode != 0:
        out["next"] = "this is not a git repository: `git init`, commit, and name the trunk `main`. " \
                      "The judge reads its rules from a commit."
        return out
    repo = Path(p.stdout.strip()).resolve()
    cfg = cfg or {}
    trunk = cfg.get("trunk", "main")
    local = cfg.get("local") or {}
    out.update(project=str(repo), trunk=trunk)

    work, work_problem = _load(repo)
    catalogs = _catalogs(repo)
    sources = {
        FILE: (repo / FILE).exists(),
        LOCAL: (repo / LOCAL).exists(),
        "backstage": {"named": _named_catalogs(repo), "found": catalogs},
    }
    out["sources"] = sources
    missing: list[str] = []
    if _git(repo, "ls-files", "--error-unmatch", LOCAL).returncode == 0:
        missing.append(f"{LOCAL} is committed: it holds held-out paths and the sandbox; remove it from git")
    elif sources[LOCAL] and _git(repo, "check-ignore", "-q", LOCAL).returncode != 0:
        missing.append(f"{LOCAL} is not in .gitignore: add it, so it is never committed")
    unread = [f for f in catalogs if f not in sources["backstage"]["named"]]
    if unread:
        missing.append(f"Backstage catalog files Morphogen does not read: {', '.join(unread)} "
                       f"(name them under `backstage:` in {FILE})")

    base_sha = None
    if _git(repo, "rev-parse", "--verify", f"{trunk}^{{commit}}").returncode == 0:
        base_sha = judge_mod.resolve(repo, trunk)
    out["base"] = base_sha

    base, base_problem = None, None
    if base_sha:
        with judge_mod.worktrees(repo, [base_sha]) as (btree,):
            base, base_problem = _load(btree)
            cells = [_cell_report(base, n, local) for n in base.doc.cells] if base else []
            errors = base.errors() if base else []
    else:
        cells, errors = [], []
    if evidence is not None:
        for c in cells:
            if c.get("ready"):
                c.update(_history(evidence, c["cell"]))
    out["cells"] = cells
    if errors:
        out["errors"] = errors
    if base_problem:
        out["errors"] = [base_problem]

    # the working tree against the trunk
    drafted = sorted(set(work.doc.cells) - set(base.doc.cells if base else ())) if work else []
    if drafted:
        out["drafted"] = drafted
    if work_problem:
        missing.append(f"{FILE} in the working tree does not load: {work_problem}")
    elif work and work.errors():
        missing.append(f"{FILE} in the working tree has errors: {'; '.join(work.errors())}")
    if base:
        untested = [i for i, spec in base.structure().interfaces.items() if not spec.tests]
        if untested:
            missing.append(f"interfaces without tests: {', '.join(sorted(untested))}")
    out["missing"] = missing
    out["next"] = _next(out, work, base, catalogs, unread)
    return out


def _next(out: dict, work: Project | None, base: Project | None, catalogs: list[str], unread: list[str]) -> str:
    trunk = out["trunk"]
    if not out["base"]:
        return f"no commit on `{trunk}` yet: commit the project there first; the judge reads its rules from it"
    if out.get("errors"):
        return f"fix the structure on `{trunk}` (the judge refuses it until then): " + "; ".join(out["errors"])
    if base is None:
        if work is not None:
            return (f"{FILE} is drafted but not on `{trunk}`: commit it on a branch and open a pull request; "
                    "the operator merges it. Until then `probe` can practise against it; no verdict rests on it")
        if catalogs:
            return (f"write {FILE} with `backstage: [{', '.join(catalogs)}]` and add, for the one part to improve, "
                    "`change`, `run`, `better` and `tests` (the map skill, step 2)")
        return ("no map yet: ask the operator what to improve and how they would know it improved, then draft "
                f"one cell in {FILE} with `change`, `run`, `better` and `tests` (the map skill)")
    ready = [c for c in out["cells"] if c.get("ready")]
    if not ready:
        broken = [c for c in out["cells"] if c.get("problems")]
        if broken:
            c = broken[0]
            return f"cell {c['cell']} is not ready to judge: {c['problems'][0]}"
        return f"no cell on `{trunk}` has a `run`: give the part to improve `change`, `run`, `better` and `tests`"
    if out.get("drafted"):
        return (f"cells drafted but not on `{trunk}`: {', '.join(out['drafted'])}; commit them on a branch for "
                "the operator to merge")
    if not any("measurements" in c for c in ready):
        c = ready[0]
        return f"measure cell:{c['cell']}, then change it on a branch, commit, and judge it"
    unmeasured = [c for c in ready if not c["measurements"] and not c["verdicts"]]
    if unmeasured:
        return f"measure cell:{unmeasured[0]['cell']} on `{trunk}`, to see where it stands"
    unjudged = [c for c in ready if not c["verdicts"] and c.get("change")]
    if unjudged:
        c = unjudged[0]
        return (f"improve cell:{c['cell']}: change it on a branch within its `change`, commit, and judge it; "
                "or tune it if its `change` has settings with ranges")
    return ("every cell on the trunk has a verdict; pick the next to improve, or map the cells around one "
            "a change could break (the map skill, step 2)")
