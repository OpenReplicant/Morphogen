"""Ranked recall over claims: one definition of a claim's searchable text, shared by the recall index
(kernel/providers/recall-bm25) and the agent interface (kernel/providers/kernel-mcp).

With the recall-bm25 provider installed (it adds `api.recall(text, int)`, D-60) ranking is BM25 over its
index; otherwise Postgres full-text search with no extension: the query is any word of the input (OR of its
lexemes), ranked by ts_rank_cd, then belief. When nothing matches, a case-insensitive substring match on
labels and subject IRIs is the fallback (short inputs, partial words, identifiers). Every statement runs
as the caller's role, so row-level security applies.

Ported from rebuild 4 modules/kernel-mcp/kernel_mcp/recall.py. Not ported yet: dense fusion (D-61) and
cross-encoder re-ranking (D-66), opt-in providers of the recall slot.
"""
from __future__ import annotations

COLUMNS = ("id, subject, predicate, object_entity, object_value, qualifiers, scope, evidence_type, "
           "attributed_to, status, belief, valid_from, valid_to")
# A claim's searchable text: its literal value, the words of its subject and object IRIs, and its
# predicate's name split at case changes (`softwareRequirements` -> "software Requirements"), so claims
# between entities are found too (D-69).
DOC = ("to_tsvector('english', coalesce(c.object_value->>'@value', '') || ' ' || "
       "regexp_replace(c.subject, '[^[:alnum:]]+', ' ', 'g') || ' ' || "
       "regexp_replace(coalesce(c.object_entity, ''), '[^[:alnum:]]+', ' ', 'g') || ' ' || "
       "regexp_replace(regexp_replace(c.predicate, '^.*[/#:]', ''), '([a-z])([A-Z])', '\\1 \\2', 'g'))")
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"

RANKED = f"""
with q as (select to_tsquery('english', coalesce(string_agg(lexeme, ' | '), '')) as tsq
           from unnest(to_tsvector('english', %(text)s)))
select coalesce(jsonb_agg(to_jsonb(r) order by r.rank desc, r.belief desc nulls last), '[]'::jsonb) from (
  select {', '.join('c.' + col for col in COLUMNS.split(', '))}, round(ts_rank_cd({DOC}, q.tsq)::numeric, 3) as rank
  from api.claims c, q
  where c.status <> 'deprecated' and {DOC} @@ q.tsq
  order by rank desc, c.belief desc nulls last limit %(n)s) r"""

SUBSTRING = f"""
select coalesce(jsonb_agg(to_jsonb(r)), '[]'::jsonb) from (
  select {COLUMNS} from api.claims
  where status <> 'deprecated' and (
    (predicate = '{LABEL}' and object_value->>'@value' ilike %(pat)s)
    or (predicate in ('{LABEL}', '{TYPE}') and subject ilike %(pat)s))
  order by (predicate = '{LABEL}') desc, subject limit %(n)s) r"""

INSTALLED = "select to_regprocedure('api.recall(text,integer)') is not null"
READY = "select exists (select 1 from recall.corpus where n > 0)"   # only once INSTALLED: the index has rows
VIA_INDEX = "select api.recall(%(text)s, %(n)s)"


def ranked(indexed: bool) -> str:
    """BM25 when the recall index is installed and has rows, else full-text search."""
    return VIA_INDEX if indexed else RANKED


def params(text: str, limit: int) -> dict:
    return {"text": text, "n": max(1, min(limit, 200)),
            "pat": "%" + text.replace("\\", "").replace("%", "").replace("_", r"\_") + "%"}


def indexed(conn) -> bool:
    """Whether the recall index is installed and has rows (a synchronous connection)."""
    return bool(conn.execute(INSTALLED).fetchone()[0] and conn.execute(READY).fetchone()[0])


def recall(conn, text: str, limit: int) -> list[dict]:
    """Ranked recall of `text` on a synchronous connection (no substring fallback: the evals measure this)."""
    return conn.execute(ranked(indexed(conn)), params(text, limit)).fetchone()[0][:limit]
