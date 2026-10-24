"""Ranked recall over claims: one definition of a claim's searchable text, shared by the recall index
(kernel/providers/recall-bm25) and the agent interface (kernel/providers/kernel-mcp).

With the recall-bm25 provider installed (it adds `api.recall(text, int)`, D-60) ranking is BM25 over its
index; otherwise Postgres full-text search with no extension: the query is any word of the input (OR of its
lexemes), ranked by ts_rank_cd, then belief. When nothing matches, a case-insensitive substring match on
labels and subject IRIs is the fallback (short inputs, partial words, identifiers). Every statement runs
as the caller's role, so row-level security applies.

With fastembed installed and its cross-encoder already in the local cache (KK_EMBED_CACHE, default
~/.cache/knowledge-kernel/fastembed), `recall` re-ranks the first POOL claims by subject (D-66, T16): a search
never downloads a model (`reranker(download=True)` does, once, from an eval's fetch or an install step), and
KK_RERANK=0 turns it off.

Ported from rebuild 4 modules/kernel-mcp/kernel_mcp/recall.py. Not ported yet: dense fusion (D-61).
"""
from __future__ import annotations

import os
import re
import sys

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


RERANKER = "jinaai/jina-reranker-v1-turbo-en"   # Apache-2.0; the best of five on SciFact (rebuild 4 D-66)
POOL = 60   # claims the cross-encoder re-scores, however few are asked for
_models: dict = {}


def cache() -> str:
    return os.environ.get("KK_EMBED_CACHE") or os.path.expanduser("~/.cache/knowledge-kernel/fastembed")


def reranker(model: str = RERANKER, download: bool = False):
    """The cross-encoder (fastembed, ONNX on CPU), loaded once from cache(). None when KK_RERANK=0, when
    fastembed is not installed, or when the model is not in the cache and `download` is false."""
    if os.environ.get("KK_RERANK") == "0":
        return None
    key = (model, download)
    if key not in _models:
        try:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
            _models[key] = TextCrossEncoder(model_name=model, cache_dir=cache(), local_files_only=not download)
        except Exception as e:   # recall keeps BM25's order; say why once
            print(f"re-ranking off: {model}: {str(e)[:200]}", file=sys.stderr)
            _models[key] = None
    return _models[key]


def words(iri: str | None) -> str:
    """An IRI's last segment as words: `pkg:pypi/psycopg` -> "psycopg", `softwareRequirements` -> "software Requirements"."""
    local = re.split(r"[/#]", iri or "")[-1]
    return " ".join(re.split(r"[^0-9A-Za-z]+", re.sub(r"([a-z])([A-Z])", r"\1 \2", local))).strip()


def literal(c: dict) -> str | None:
    value = (c.get("object_value") or {}).get("@value") if isinstance(c.get("object_value"), dict) else None
    return str(value) if value else None


def passage(c: dict) -> str:
    """What the cross-encoder reads of a claim: its literal value, else its subject, predicate, object and
    qualifiers as words."""
    return literal(c) or " ".join(filter(None, [words(c.get("subject")), words(c.get("predicate")),
                                                words(c.get("object_entity")),
                                                *(f"{words(k)} {v}" for k, v in (c.get("qualifiers") or {}).items())]))


TEXTS = """select coalesce(jsonb_object_agg(subject, text), '{}'::jsonb) from (
  select subject, left(string_agg(object_value->>'@value', E'\n' order by length(object_value->>'@value'), id), 3000) as text
  from api.claims where subject = any(%(subjects)s) and status <> 'deprecated' and object_value ? '@value'
  group by subject) t"""


def rerank(text: str, claims: list[dict], limit: int, texts: dict[str, str] | None = None) -> list[dict]:
    """The first `limit` claims, re-ordered by the cross-encoder: per subject, its text (`texts`: all its
    literal claims, shortest first; else its recalled claims' passages) scored against `text`. Subjects go in
    score order, each with its recalled claims; claims after the first POOL keep their place."""
    ce = reranker()
    if ce is None or len(claims) < 2:
        return claims[:limit]
    head, tail = claims[:POOL], claims[POOL:]
    groups: dict[str, list[dict]] = {}
    for c in head:
        groups.setdefault(c.get("subject") or "", []).append(c)
    keys = list(groups)
    docs = ["\n".join(dict.fromkeys(filter(None, [(texts or {}).get(k), *(passage(c) for c in groups[k]
                                                                          if not (texts and literal(c)))])))[:3000]
            for k in keys]
    scores = list(ce.rerank(text, docs))
    order = sorted(range(len(keys)), key=lambda i: -scores[i])
    return ([c for i in order for c in groups[keys[i]]] + tail)[:limit]


def recall(conn, text: str, limit: int) -> list[dict]:
    """Ranked recall of `text` on a synchronous connection (no substring fallback: the evals measure this):
    BM25 (or full-text search), re-ranked when there is a cross-encoder and the index."""
    on = indexed(conn)
    rerank_on = on and reranker() is not None
    rows = conn.execute(ranked(on), params(text, max(limit, POOL) if rerank_on else limit)).fetchone()[0]
    if not rerank_on:
        return rows[:limit]
    subjects = list(dict.fromkeys(c.get("subject") or "" for c in rows[:POOL]))
    return rerank(text, rows, limit, conn.execute(TEXTS, {"subjects": subjects}).fetchone()[0])
