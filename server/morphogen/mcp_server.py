"""Morphogen's MCP server: the tools an agent harness uses, and the judge it cannot edit.

The agent may read and write the lists (what is known) and add its own notes
to the evidence log, which are always recorded as inferred. Only the judge,
running here, writes measured evidence.
"""

from __future__ import annotations

import functools
from typing import Any

from mcp.server.mcpserver import MCPServer

from . import admin as admin_mod
from . import judge as judge_mod
from . import project
from . import strategies as strategies_mod
from . import telemetry
from .config import load_config, project_root

server = MCPServer(
    name="morphogen",
    instructions=(
        "Morphogen maps, measures and improves systems. Use doctor first. Lists hold what is known "
        "(systems, slots, types, sources, components). Evidence holds claims with their support; only "
        "the judge writes measured evidence. To improve a target: measure it, change it on a branch, "
        "commit, then call judge(target, base, candidate). Merging is the operator's decision."
    ),
)


def _ctx():
    root = project_root()
    return root, load_config(root)


def _safe(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except (judge_mod.JudgeError, ValueError, RuntimeError) as e:
            return {"error": str(e)}
    return wrapper


@server.tool()
@_safe
def doctor() -> dict:
    """Report the project, backend, evidence chain, sandbox and which guarantees are actually active."""
    root, _ = _ctx()
    return project.doctor(root)


@server.tool()
@_safe
def init_project() -> dict:
    """Set up Morphogen in this project: morphogen.yaml, data directory, seed lists, catalogs.yaml."""
    root, _ = _ctx()
    return project.init_project(root)


@server.tool()
@_safe
def install_sample(name: str = "slow-script", dest: str | None = None) -> dict:
    """Copy a sample target into the project (default: targets/<name>) and register it."""
    root, _ = _ctx()
    return project.install_sample(root, name, dest)


@server.tool()
@_safe
def lists_get(kind: str, id: str) -> dict:
    """Get one entry. kind: systems | slots | types | sources | components. An id like
    `homelab:comp/gpu-box` reads from a mounted map (see the maps tool)."""
    root, cfg = _ctx()
    lists, _ = project.stores(root, cfg)
    return lists.get(kind, id) or {"error": f"no {kind} entry {id!r}"}


@server.tool()
@_safe
def lists_put(kind: str, entry: dict[str, Any], reason: str | None = None) -> dict:
    """Add or replace an entry (needs an 'id') in this project's map. References to other entries are
    their ids; `map:id` refers to an entry in a mounted map. Mounted maps are read-only.
    Every write is recorded in the change log; `reason` (for example `evidence:42`) says why."""
    root, cfg = _ctx()
    lists, _ = project.stores(root, cfg)
    return lists.put(kind, entry, by="agent", reason=reason)


@server.tool()
@_safe
def lists_history(kind: str | None = None, id: str | None = None, limit: int = 50) -> dict:
    """Recorded writes to this project's map, newest first: what changed (hashes before and after, the new
    entry), who wrote it and why. Filter by list (`kind`) and `id`."""
    root, cfg = _ctx()
    lists, _ = project.stores(root, cfg)
    return {"changes": lists.history(kind, id, limit)}


@server.tool()
@_safe
def lists_query(kind: str, where: dict[str, Any] | None = None, follow: str | None = None,
                start: str | None = None, hops: int = 1, map: str | None = None) -> dict:
    """Query a list. `where` matches fields exactly, or by substring with a leading '~'.
    With `follow` and `start`, return entries reachable from `start` along reference field `follow`,
    across maps. `map`: a mounted map's name, or '*' for all maps; default this project's map.
    Entries from mounted maps carry `_map` and `_trust: stated`."""
    root, cfg = _ctx()
    lists, _ = project.stores(root, cfg)
    if follow and start:
        return {"results": lists.follow(kind, start, follow, hops)}
    return {"results": lists.query(kind, where, map=map)}


@server.tool()
@_safe
def maps() -> dict:
    """This project's map and the maps mounted from morphogen.yaml: source, whether each is pinned to a
    commit, entry counts, errors, and references (in any map) that do not resolve."""
    root, cfg = _ctx()
    lists, _ = project.stores(root, cfg)
    return lists.status()


@server.tool()
@_safe
def evidence_query(contains: str | None = None, by: str | None = None, limit: int = 20) -> dict:
    """Most recent evidence first. Filter by text and by author ('judge', 'agent', 'operator')."""
    root, cfg = _ctx()
    _, evidence = project.stores(root, cfg)
    return {"results": evidence.query(contains, by, limit)}


@server.tool()
@_safe
def evidence_note(claim: str, source: str, trust: str = "inferred",
                  supports: list[int] | None = None, challenges: list[int] | None = None) -> dict:
    """Record a claim that was not measured: 'inferred' (reasoned) or 'stated' (from docs).
    supports/challenges list the evidence seq numbers this claim agrees or disagrees with."""
    if trust not in ("inferred", "stated"):
        return {"error": "notes can only be 'inferred' or 'stated'; measured evidence comes from the judge"}
    root, cfg = _ctx()
    _, evidence = project.stores(root, cfg)
    return evidence.append({"claim": claim, "kind": "note", "source": source, "trust": trust,
                            "supports": supports or [], "challenges": challenges or [], "by": "agent"})


@server.tool()
@_safe
def catalog_search(query: str = "", limit: int = 20, slot: str | None = None) -> dict:
    """Search catalogs.yaml and the sources, components and types lists before building anything new.
    With `slot`, list what could fill that slot instead: components and catalog entries of an accepted
    type, ranked by whether they provide every capability the slot `requires`, then by fewest missing,
    then by fewest extra capabilities (overhead the design does not call for)."""
    root, cfg = _ctx()
    if slot:
        return project.candidates(root, cfg, slot, limit)
    return {"results": project.catalog_search(root, cfg, query, limit)}


@server.tool()
@_safe
def measure(target: str, ref: str = "HEAD") -> dict:
    """Benchmark a target at a commit with the judge's hidden seed; recorded as measured evidence."""
    root, cfg = _ctx()
    _, evidence = project.stores(root, cfg)
    with telemetry.span("morphogen.measure", target=target, ref=ref) as s:
        out = judge_mod.measure(root, cfg, target, ref, evidence)
        if s is not None:
            s.set_attribute("morphogen.trust", out.get("trust", ""))
        return out


@server.tool()
@_safe
def judge(target: str, candidate: str = "HEAD", base: str | None = None,
          labels: dict[str, str] | None = None) -> dict:
    """Score a candidate commit against a base (default: the trunk) using the base's tests, harness
    and freshly generated inputs. Passes only if tests pass, outputs match, and the primary metric
    improves by its bar, beyond chance, without other metrics regressing. The verdict is recorded.
    labels: optional {strategy, approach, family, parent} for the archive; they never affect the verdict.
    A target with `interface: simulated` gets verdicts with trust 'simulated': evidence about the model,
    not reality."""
    root, cfg = _ctx()
    _, evidence = project.stores(root, cfg)
    with telemetry.span("morphogen.judge", target=target, candidate=candidate,
                        strategy=(labels or {}).get("strategy")) as s:
        out = judge_mod.judge(root, cfg, target, base or cfg.get("trunk", "main"), candidate, evidence, labels)
        if s is not None:
            s.set_attribute("morphogen.verdict", out["verdict"])
            for metric, c in out.get("metrics", {}).items():
                s.set_attribute(f"morphogen.gain.{metric}", c["gain"])
        return out


@server.tool()
@_safe
def probe(target: str, candidate: str = "HEAD", base: str | None = None, cases: int = 5, rounds: int = 3) -> dict:
    """Practice run on a candidate, for strategies that learn from failures: under the judge's rules,
    returns the check's output, each generated case (with expected and actual output where they differ)
    and a few paired timing rounds. Never a verdict and never mergeable; use judge for that."""
    root, cfg = _ctx()
    _, evidence = project.stores(root, cfg)
    return judge_mod.probe(root, cfg, target, candidate, evidence, base, cases, rounds)


@server.tool()
@_safe
def strategy(target: str) -> dict:
    """Which improvement strategy to follow for the next round on a target, why, and its card.
    'auto' in morphogen.yaml picks from evidence; a name there forces that strategy."""
    root, cfg = _ctx()
    _, evidence = project.stores(root, cfg)
    return strategies_mod.choose(root, cfg, evidence, target)


@server.tool()
@_safe
def archive(target: str, limit: int = 30) -> dict:
    """Judged variants of a target, newest last, with lineage, labels, verdicts and primary gains;
    plus how many children each commit has and the payoff of each strategy."""
    root, cfg = _ctx()
    _, evidence = project.stores(root, cfg)
    variants = strategies_mod.archive(evidence, target)
    return {"variants": variants[-limit:], "children": strategies_mod.children(variants),
            "payoff": strategies_mod.payoff(variants)}


@server.tool()
@_safe
def strategies_list() -> dict:
    """The strategy catalog: the plugin's cards plus any in the project's strategies/ directory."""
    root, _ = _ctx()
    return {"strategies": [{k: v for k, v in c.items() if k != "body"}
                           for c in strategies_mod.catalog(root).values()]}


@server.tool()
@_safe
def journal_append(title: str, gap: str, options: str, choice: str, rung: str,
                   gate: str = "", commit: str = "", why: str = "") -> dict:
    """Append a journal entry: the gap, options considered, the choice and why, the sourcing rung
    (reuse | configure | compose | generate), the judge's result and the commit."""
    root, cfg = _ctx()
    return project.journal_append(root, cfg, {"title": title, "gap": gap, "options": options,
                                              "choice": choice, "why": why, "rung": rung,
                                              "gate": gate, "commit": commit})


@server.tool()
@_safe
def admin_pages() -> dict:
    """Write the admin menu (what fills each admin-ui slot, links open in new tabs) and a read-only
    report (map, evidence chain, archive lineage) as static HTML in the data directory."""
    root, cfg = _ctx()
    return admin_mod.write(root, cfg)


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
