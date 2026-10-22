"""Map-quality report for a target environment: coverage, precision, freshness, drift.

    uv run morphogen-report [--environment sandbox] [--json]

Reads the map through MORPHOGEN_READ_DATABASE_URL (the reader role).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from morphogen import queries


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="morphogen-report", description=__doc__.splitlines()[0])
    ap.add_argument("--environment", default="sandbox")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    dsn = os.environ.get("MORPHOGEN_READ_DATABASE_URL")
    if not dsn:
        print("set MORPHOGEN_READ_DATABASE_URL (reader role)", file=sys.stderr)
        return 2
    from morphogen.store.postgres import PostgresStore

    store = PostgresStore(dsn, slot="report")
    m = queries.metrics(store, args.environment)
    d = queries.drift(store, args.environment)
    if args.json:
        print(json.dumps({"metrics": m, "drift": d}, indent=2, default=str))
        return 0
    pct = lambda v: "n/a" if v is None else f"{v:.0%}"
    fresh = m["freshness_s"] or {}
    print(f"environment   {m['environment']}")
    print(f"coverage      {pct(m['coverage'])}  ({m['expected_couplings']} expected couplings)")
    print(f"precision     {pct(m['precision'])}  ({m['observed_couplings']} observed couplings)")
    print(f"freshness     median {fresh.get('median', 'n/a')}s, max {fresh.get('max', 'n/a')}s")
    print(f"drift         {m['drift']['intended_not_observed']} expected not observed, "
          f"{m['drift']['observed_not_intended']} observed not expected")
    for label, items in (("missing", d["intended_not_observed"]), ("unexpected", d["observed_not_intended"])):
        for i in items:
            what = f"{i['source_slot']} -> {i['target_slot']}" if i["what"] == "coupling" else i["name"]
            print(f"  {label:<10} {i['what']:<8} {what}  [{i['status']}] {i['key']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
