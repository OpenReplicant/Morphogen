"""Mutants the recall slot's case set (kernel/contract/slots/recall) must kill (kernel/contract/mutants.py)."""
M = "recall_bm25/__main__.py"
SQL = "migration.sql"
MUTANTS = [
    ("api.recall reads as its owner, not the reader", SQL, [
        ("returns jsonb\nlanguage sql stable security invoker", "returns jsonb\nlanguage sql stable security definer")]),
    ("retracted claims returned", SQL, [("    where c.status <> 'deprecated'\n", "")]),
    ("redacted claims stay in the index", M, [("            dropped = conn.execute(FORGET).fetchone()[0]", "            dropped = 0")]),
    ("only the first pass indexes", M, [("    and (%(since)s::timestamptz is null or c.recorded_at >= %(since)s)",
                                         "    and %(since)s::timestamptz is null")]),
    ("the limit is ignored", SQL, [("    limit greatest(1, least(p_limit, 200))) r", "    limit 200) r")]),
    ("worst first", SQL, [("jsonb_agg(to_jsonb(r) order by r.rank desc,", "jsonb_agg(to_jsonb(r) order by r.rank asc,")]),
]
