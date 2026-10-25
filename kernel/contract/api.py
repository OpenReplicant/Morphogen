"""The kernel's wire API, versioned (T25, R5-42 (b)): what a provider, a distribution or an agent built against the
record store may rely on. kernel/contract/api.yaml lists it, read from a fresh record (record-postgres's schema, no
provider installed):

  functions  every function in schema api, and every non-trigger function in schema kernel that kk_agent may execute,
             with its arguments and result
  relations  every view in schema api, and every table or view in schema kernel that kk_agent may read, with its columns
  version    semantic: a change that removes or changes anything listed is a major version, an addition a minor one;
             api.version() returns it, so a client can check what it talks to
  change_set the change-set schema's $id (kernel/schemas/change_set.schema.json); the MCP tools agents rely on are the
             agent-interface slot's (contract/slots/agent-interface/set.yaml `tools`)

  python3 kernel/contract/api.py check            # fails when the record and api.yaml differ, or the versions do
  python3 kernel/contract/api.py write VERSION    # rewrite api.yaml; refused when the surface changed and VERSION did not
Uses the PG* environment, like psql; run as a superuser. kernel/contract/run.sh runs `check` first.
"""
import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "slots"))
from harness import Record  # noqa: E402

FILE = HERE / "api.yaml"
SCHEMA = HERE.parent / "schemas" / "change_set.schema.json"

FUNCTIONS = """
select n.nspname || '.' || p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')' as name,
       pg_get_function_result(p.oid) as result
from pg_proc p join pg_namespace n on n.oid = p.pronamespace
where (n.nspname = 'api'
       or (n.nspname = 'kernel' and p.prorettype <> 'trigger'::regtype and has_function_privilege('kk_agent', p.oid, 'execute')))
order by 1"""
RELATIONS = """
select n.nspname || '.' || c.relname as name,
       array_agg(a.attname || ' ' || format_type(a.atttypid, a.atttypmod) order by a.attnum) as columns
from pg_class c join pg_namespace n on n.oid = c.relnamespace
join pg_attribute a on a.attrelid = c.oid and a.attnum > 0 and not a.attisdropped
where c.relkind in ('r', 'v', 'p') and (n.nspname = 'api' or (n.nspname = 'kernel' and has_table_privilege('kk_agent', c.oid, 'select')))
group by 1 order by 1"""


def surface() -> tuple[dict, str]:
    rec = Record("kkc_api", [], packs=False)
    try:
        functions = {r["name"]: r["result"] for r in rec.rows(FUNCTIONS)}
        relations = {r["name"]: list(r["columns"]) for r in rec.rows(RELATIONS)}
        version = rec.rows("select api.version() v")[0]["v"]
    finally:
        rec.drop()
    return {"functions": functions, "relations": relations,
            "change_set": json.loads(SCHEMA.read_text()).get("$id")}, version


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in ("check", "write") or (argv[0] == "write" and len(argv) != 2):
        print(__doc__)
        return 2
    now, version = surface()
    listed = yaml.safe_load(FILE.read_text()) if FILE.exists() else {}
    before = {k: listed.get(k) for k in ("functions", "relations", "change_set")}
    if argv[0] == "check":
        problems = []
        for kind in ("functions", "relations"):
            a, b = before[kind] or {}, now[kind]
            problems += [f"{kind}: {n} is in api.yaml but not in the record" for n in sorted(set(a) - set(b))]
            problems += [f"{kind}: {n} is in the record but not in api.yaml" for n in sorted(set(b) - set(a))]
            problems += [f"{kind}: {n} changed" for n in sorted(set(a) & set(b)) if a[n] != b[n]]
        if before["change_set"] != now["change_set"]:
            problems.append(f"change_set: {before['change_set']} in api.yaml, {now['change_set']} in the schema")
        if listed.get("version") != version:
            problems.append(f"version: {listed.get('version')} in api.yaml, {version} from api.version()")
        for p in problems:
            print(f"api: {p}")
        print(f"api: {'FAIL' if problems else 'ok'}: the record's API is version {version}"
              + (" (run `api.py write <version>` with the version the change needs, and update api.version())" if problems else ""))
        return 1 if problems else 0
    new = argv[1]
    if before != now and new == listed.get("version"):
        print(f"api: the surface changed: give a new version (now {new}): major when anything listed was removed or changed")
        return 1
    if new != version:
        print(f"api: api.version() returns {version}; change it to {new} in record-postgres's schema first")
        return 1
    head = "\n".join("# " + line if line else "#" for line in __doc__.strip().splitlines()[:12])
    FILE.write_text(head + "\n" + yaml.safe_dump({"version": new, **now}, sort_keys=False, width=200))
    print(f"api: wrote {FILE} at version {new}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
