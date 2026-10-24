"""Dependency reasoning over recorded claims (R5-O7 a2, T19): a property, every property declared
`rdfs:subPropertyOf` it (transitively, from the packs in the record), and the transitive closure of the
edges they make.

  subproperties(cur, prop)                        -> {prop, its subproperties}
  edges(cur, prop, agents=None)                   -> [(subject, object, claim id)], current claims only
  closure(edge_list, start, reverse=False)        -> {node: [claim ids on the shortest path from start]}

Only current claims count (not deprecated, not redacted), and only those the caller may read (the store's
row security). `agents` keeps the edges recorded by those agents (a map's encoders). closure is pure: a
cycle ends where it closes, the start is not in its own closure, and ties break by node name, so the same
edges always give the same paths. reverse=True follows edges backwards: who depends on `start`.
"""
from __future__ import annotations

from typing import Iterable, Optional

SUBPROPERTY = "http://www.w3.org/2000/01/rdf-schema#subPropertyOf"
DEPENDS_ON = "https://w3id.org/knowledge-kernel/tosca#dependsOn"


def subproperties(cur, prop: str) -> set[str]:
    cur.execute("""with recursive sub(p) as (
                     select %s::text
                     union
                     select c.subject from api.claims c join sub on c.object_entity = sub.p
                      where c.predicate = %s and c.status <> 'deprecated' and c.redacted_at is null)
                   select p from sub""", (prop, SUBPROPERTY))
    return {r[0] for r in cur.fetchall()}


def edges(cur, prop: str = DEPENDS_ON, agents: Optional[Iterable[str]] = None) -> list[tuple[str, str, str]]:
    props = sorted(subproperties(cur, prop))
    q = """select subject, object_entity, id::text from api.claims
            where predicate = any(%s) and object_entity is not null and status <> 'deprecated' and redacted_at is null"""
    args: list = [props]
    if agents is not None:
        q += " and attributed_to = any(%s)"
        args.append(list(agents))
    cur.execute(q + " order by subject, object_entity, id", args)
    return [(s, o, i) for s, o, i in cur.fetchall()]


def closure(edge_list: Iterable[tuple[str, str, str]], start: str, reverse: bool = False) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for s, o, i in edge_list:
        a, b = (o, s) if reverse else (s, o)
        out.setdefault(a, []).append((b, i))
    paths, frontier = {start: []}, [start]
    while frontier:
        nxt = []
        for node in frontier:
            for other, claim in sorted(out.get(node, [])):
                if other not in paths:
                    paths[other] = paths[node] + [claim]
                    nxt.append(other)
        frontier = sorted(nxt)
    del paths[start]
    return paths
