"""SPARQL as pySHACL runs it, made affordable: every SHACL user in the kernel (the validator, the gap finder) calls
`prepare_queries()` once.

pySHACL runs each SPARQL-based constraint once per focus node, as a query string, and rdflib parses the string every
time: 70% of validating a large change set (rebuild 4, M3-T4), and a 200-service map took the gap finder 6 s against
0.95 s with this (R5-O18 (5)). Each distinct query is translated once and reused with each node's bindings, as
rdflib's prepared queries are meant to be used. Patching rdflib's processor is process-wide and idempotent.
"""
from __future__ import annotations

from functools import lru_cache

_done = False


def prepare_queries() -> None:
    global _done
    if _done:
        return
    from rdflib.plugins.sparql import processor

    @lru_cache(maxsize=256)
    def prepared(text: str, base, ns: tuple):
        return processor.translateQuery(processor.parseQuery(text), base, dict(ns))

    query = processor.SPARQLProcessor.query

    def cached(self, strOrQuery, initBindings=None, initNs=None, base=None, DEBUG=False):
        if isinstance(strOrQuery, str):
            strOrQuery = prepared(strOrQuery, base, tuple(sorted((initNs or {}).items())))
        return query(self, strOrQuery, initBindings, initNs, base, DEBUG)
    processor.SPARQLProcessor.query = cached
    _done = True
