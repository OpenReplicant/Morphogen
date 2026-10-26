"""Query-time mappings (R5-O13 (1), R5-51): the terms a reader may count as a term it was asked about, and the
mapping claims each rests on.

  CURRENT                      SQL: every current mapping claim the caller may read (subject, predicate, object, id)
  reach(rows, term)            -> {term: [mapping claim ids on the shortest way from the asked term]}
  equivalents(cur, term)       reach() over the record, as the cursor's role

Only current claims count (not deprecated, not redacted): a mapping is in the record only once a person approved
it or it came with a pack (the lane policy sends every skos:*Match to review), and a refuted or retracted one is
no longer followed. What is followed, from the asked term:
  skos:exactMatch    either way, and on from there (transitive);
  skos:broadMatch    from the narrower term up: `Y broadMatch X` lets a question about X count Y (and on, as
  skos:narrowMatch   SSSOM's chaining rules take both as transitive); `X narrowMatch Y` the same;
  skos:closeMatch    either way, at most once on any way (it is not transitive);
  skos:relatedMatch  never.
A question about the narrower term never counts the broader one. The ids returned are what an answer reached
through a mapping cites (invariant 6); the asked term itself rests on none.
"""
from __future__ import annotations

from collections import deque
from typing import Iterable

SKOS = "http://www.w3.org/2004/02/skos/core#"
EXACT, CLOSE, BROAD, NARROW, RELATED = (SKOS + n for n in ("exactMatch", "closeMatch", "broadMatch", "narrowMatch", "relatedMatch"))
MATCHES = [EXACT, CLOSE, BROAD, NARROW, RELATED]

CURRENT = """select subject, predicate, object_entity, id::text from api.claims
              where predicate = any(%(matches)s) and object_entity is not null
                and status <> 'deprecated' and redacted_at is null
              order by subject, predicate, object_entity, id"""


def _steps(rows: Iterable[tuple[str, str, str, str]]) -> dict[str, list[tuple[str, bool, str]]]:
    """term -> [(next term, is a closeMatch, claim id)]: the ways a question about `term` may widen."""
    out: dict[str, list[tuple[str, bool, str]]] = {}
    for s, p, o, i in rows:
        if p in (EXACT, CLOSE):
            out.setdefault(s, []).append((o, p == CLOSE, i))
            out.setdefault(o, []).append((s, p == CLOSE, i))
        elif p == BROAD:                       # s is narrower than o: asking about o counts s
            out.setdefault(o, []).append((s, False, i))
        elif p == NARROW:                      # o is narrower than s: asking about s counts o
            out.setdefault(s, []).append((o, False, i))
    for v in out.values():
        v.sort()
    return out


def reach(rows: Iterable[tuple[str, str, str, str]], term: str) -> dict[str, list[str]]:
    """Every term a question about `term` counts, with the mapping claim ids on the shortest way to it (ties by
    term and id, so the same mappings always give the same answer). Pure."""
    steps = _steps(rows)
    found: dict[str, list[str]] = {term: []}
    seen = {(term, False)}
    queue = deque([(term, False, [])])
    while queue:
        t, closed, path = queue.popleft()
        for nxt, close, cid in steps.get(t, []):
            if close and closed:
                continue
            state = (nxt, closed or close)
            if state in seen:
                continue
            seen.add(state)
            way = path + [cid]
            found.setdefault(nxt, way)
            queue.append((nxt, closed or close, way))
    return found


def equivalents(cur, term: str) -> dict[str, list[str]]:
    cur.execute(CURRENT, {"matches": MATCHES})
    return reach(cur.fetchall(), term)
