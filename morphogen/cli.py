"""Command line.

    morphogen status
    morphogen structure check|scope|render FILE [CELL] [--observed FILE]
    morphogen measure TARGET [--ref main]
    morphogen judge TARGET CANDIDATE [--base main]
    morphogen request FILE          # one document: what to judge, and the operator's local settings
    morphogen pr --base B --head H --sandbox docker --out FILE   # a pull request, as the GitHub judge runs it
    morphogen tune TARGET [--optimizer NAME] [--steps N] [--trials N]
    morphogen optimizers
    morphogen evidence [--verify] [--limit N] [--by judge]
    morphogen ui [--host 127.0.0.1] [--port 8765]
    morphogen site init [ROOT] [--repo OWNER/NAME] [--system system:default/NAME]   # a starter research site config
    morphogen site build --config FILE --out DIR [--base /prefix]                  # the static research site

TARGET is `cell:NAME` for a cell with a `run` in the catalog (`spec.morphogen.run` on its entity) (or the cell's name, or its `dir`).
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
                "tests": s.tests_for_cell(a.cell), "neighbours": s.neighbours(a.cell)})
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


def cmd_change(a) -> int:
    root = _root()
    r = judge_mod.judge_change(root, load_config(root), a.base, a.candidate, Evidence.for_project(root))
    _print(r)
    return 0 if r["verdict"] == "pass" else 1


def cmd_request(a) -> int:
    from .request import run as run_request
    r = run_request(Path(a.file))
    _print(r)
    return 0 if r.get("verdict", "pass") == "pass" else 1


def cmd_pr(a) -> int:
    from .pullrequest import main as pr_main
    return pr_main(a)


def cmd_intake(a) -> int:
    from . import intake
    home = Path(a.home) if a.home else Path.home()
    if a.action == "advance":
        _print(intake.advance(home, a.name, sys.stdin.buffer))
        return 0
    r = intake.judge(home, a.name, sys.stdin.buffer)
    _print(r)
    return 0 if r.get("verdict", "pass") == "pass" else 1


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


def cmd_site(a) -> int:
    from . import site
    try:
        if a.action == "init":
            _print(site.init(a.root, repo=a.repo, system=a.system, title=a.title, owner=a.owner, config=a.config_name,
                             content=a.content, force=a.force))
        else:
            if not a.config or not a.out:
                print("morphogen: site build needs --config and --out", file=sys.stderr)
                return 2
            print(f"Built {site.build(a.config, a.out, a.base or '', install=a.install)}")
    except site.SiteError as e:
        print(f"morphogen: {e}", file=sys.stderr)
        return 2
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

    ch = sub.add_parser("change", help="judge a change that claims no improvement: the cells its files belong "
                        "to, default deny, and the tests of every interface those cells touch, by the base's rules")
    ch.add_argument("candidate")
    ch.add_argument("--base", default="main")
    ch.set_defaults(fn=cmd_change)

    rq = sub.add_parser("request", help="do what a request file asks (judge, change, probe or measure): the rules "
                        "from the base commit, the local settings from the request; the verdict records its digest")
    rq.add_argument("file", help="a request/v1 document, outside the repository")
    rq.set_defaults(fn=cmd_request)

    pr = sub.add_parser("pr", help="judge a pull request without a person at the keyboard (the GitHub judge): "
                        "not judged, refused, or a request to the judge; the verdict document always written to --out")
    pr.add_argument("--base", required=True, help="the base: where the rules come from")
    pr.add_argument("--head", required=True, help="the pull request's head commit")
    pr.add_argument("--sandbox", required=True, choices=["podman", "docker", "none"],
                    help="where candidates run; none only with --unsandboxed")
    pr.add_argument("--local", help="the operator's morphogen.local.yaml, outside the repository (held-out answers, "
                    "inputs, env, services); relative paths in it are read from its directory")
    pr.add_argument("--target", help="what to judge (cell:NAME); else a `morphogen-target:` line in --body-env, "
                    "else the change is judged as one that claims no improvement")
    pr.add_argument("--body-env", help="an environment variable holding the pull request's description")
    pr.add_argument("--protect", action="append", help="a glob no pull request may change (repeatable)")
    pr.add_argument("--label", action="append", help="KEY=VALUE recorded with the verdict, never deciding it")
    pr.add_argument("--pull", action="store_true", help="pull the sandbox image before any run")
    pr.add_argument("--unsandboxed", action="store_true", help="allow --sandbox none (tests and local trials only)")
    pr.add_argument("--out", required=True, help="where to write the pr-verdict/v1 document")
    pr.set_defaults(fn=cmd_pr)

    it = sub.add_parser("intake", help="the judge held by another user: judge the candidate bundled on standard "
                        "input by a request that user keeps, or (the owner's) advance its base")
    it.add_argument("action", choices=["judge", "advance"])
    it.add_argument("name", help="the request's name: HOME/requests/NAME.yaml on the judge's side")
    it.add_argument("--home", help="the judge's home (default: the home of the user running this)")
    it.set_defaults(fn=cmd_intake)

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

    si = sub.add_parser("site", help="the research site: init writes a starter config and content folder into a "
                        "research project; build makes the static site from a config (site/README.md)")
    si.add_argument("action", choices=["init", "build"])
    si.add_argument("root", nargs="?", default=".", help="for init: the research project (catalog-info.yaml, "
                    "claims/, research/); default: here")
    si.add_argument("--config", help="for build: the site's config file")
    si.add_argument("--out", help="for build: the folder to write the HTML into")
    si.add_argument("--base", help="for build: the path the site is served under, e.g. /research (default: "
                    "relative links, which work under any path)")
    si.add_argument("--install", action="store_true", help="for build: run npm ci in site/ first if needed")
    si.add_argument("--repo", help="for init: OWNER/NAME for steering issues (default: the origin remote)")
    si.add_argument("--system", help="for init: the System to assess against (default: catalog-info.yaml's)")
    si.add_argument("--title", help="for init: the site's title")
    si.add_argument("--owner", help="for init: whose research it is (default: the repo's owner)")
    si.add_argument("--config-name", default="site.toml", help="for init: the config file, in ROOT")
    si.add_argument("--content", default="site", help="for init: the content folder, in ROOT")
    si.add_argument("--force", action="store_true", help="for init: replace existing files")
    si.set_defaults(fn=cmd_site)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except (StructureError, DocumentError, ProjectError, judge_mod.JudgeError, KeyError, LookupError) as e:
        print(f"morphogen: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
