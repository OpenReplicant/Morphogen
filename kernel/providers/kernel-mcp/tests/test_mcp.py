"""The kernel MCP server over stdio, as one agent's own login (rebuild 4 scripts/e2e_kernel.py, operator tools).

An agent starts a run and submits a claim through MCP; the validator applies it; the agent finds it with
search (BM25 once the recall index has it) and query_claims, each with id and belief, and explains it back
to its source. A login that can switch roles (a superuser) is refused.

  PGHOST=... PGUSER=<superuser> python3 kernel/providers/kernel-mcp/tests/test_mcp.py
"""
import asyncio
import importlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROVIDERS = HERE.parents[1]
for p in (PROVIDERS.parent / "src", PROVIDERS, PROVIDERS / "validator-shacl", PROVIDERS / "recall-bm25"):
    sys.path.insert(0, str(p))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

import install  # noqa: E402
from kk.lib import connect  # noqa: E402

validator = importlib.import_module("validator.__main__")
recall_index = importlib.import_module("recall_bm25.__main__")

DB = "kk_mcp_test"
ROLE = AGENT_PASSWORD = "t_mcp_agent"
AGENT = "urn:kk:agent:test-mcp"
TOOLS = {"query_claims", "get_entity", "search", "explain", "list_slots", "list_modules", "start_run",
         "submit_change_set", "get_change_set", "list_runs", "finish_run", "whoami", "list_change_sets",
         "review_queue", "review", "graph"}


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}")


def server(login: str) -> StdioServerParameters:
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "PGHOST", "PGPORT")}
    env.update(PYTHONPATH=os.pathsep.join([str(PROVIDERS.parent / "src"), str(PROVIDERS / "kernel-mcp")]),
               KK_DATABASE_URL=login)
    return StdioServerParameters(command=sys.executable, args=["-m", "kernel_mcp"], env=env)


async def call(s: ClientSession, tool: str, args: dict | None = None):
    res = await s.call_tool(tool, args or {})
    if res.is_error:
        return {"error": res.content[0].text if res.content else "error"}
    sc = res.structured_content
    return sc.get("result", sc) if isinstance(sc, dict) else json.loads(res.content[0].text)


async def agent_session(login: str) -> None:
    async with stdio_client(server(login)) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        names = {t.name for t in (await s.list_tools()).tools}
        check(names == TOOLS, "the operator tools are listed, and no memory-profile tool")
        me = await call(s, "whoami")
        check(me["agent"] == AGENT and me["role"] == ROLE, "whoami is the agent's own login and IRI")
        run_id = await call(s, "start_run", {"module": "urn:kk:module:test-mcp"})
        cs = await call(s, "submit_change_set", {"change_set": {
            "idempotency_key": "mcp:1", "attributed_to": AGENT, "generated_by": run_id,
            "target_scope": "urn:kk:scope:default",
            "ops": [{"op": "add_claim", "subject": "urn:x:billing", "predicate": "rdfs:label",
                     "object": {"value": {"@value": "Billing ledger service"}}, "evidence_type": "deterministic",
                     "references": [{"source_uri": "https://example.org/services"}]}]}})
        check(cs.get("status") == "submitted", "a change set submitted through MCP starts as submitted")
        spoof = await call(s, "submit_change_set", {"change_set": {
            "idempotency_key": "mcp:spoof", "attributed_to": "urn:kk:agent:validator", "generated_by": run_id,
            "target_scope": "urn:kk:scope:default", "ops": [{"op": "add_entity", "iri": "urn:x:y"}]}})
        check("error" in spoof and "refused" in spoof["error"], "the kernel refuses a change set attributed to someone else")

        with connect("kkm_validator", f"dbname={DB}") as val:
            validator.drain(val)
        with connect("kkm_recall_index", f"dbname={DB}") as idx:
            recall_index.Pass()(idx)

        hits = await call(s, "search", {"text": "ledger"})
        hit = next((h for h in hits if h["subject"] == "urn:x:billing"), None)
        check(hit is not None and "belief" in hit and hit.get("rank") is not None,
              "search finds the claim by BM25, with its id, belief and rank")
        found = await call(s, "query_claims", {"subject": "urn:x:billing", "predicate": "rdfs:label"})
        check(len(found) == 1 and found[0]["id"] == hit["id"], "query_claims returns the same claim")
        why = await call(s, "explain", {"claim_id": hit["id"][:8]})
        check(why["references"][0]["source_uri"] == "https://example.org/services" and why["run"]["id"] == run_id,
              "explain (by the first characters of the id) shows the source and the run")
        status = await call(s, "get_change_set", {"change_set_id": cs["id"]})
        check(status["status"] == "applied", "get_change_set shows it applied")
        await call(s, "finish_run", {"run_id": run_id})


async def refused(login: str, what: str) -> None:
    async with stdio_client(server(login)) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        res = await call(s, "whoami")
        check("error" in res and "own login" in res["error"], f"{what} is refused")


async def reviewer_session(login: str) -> None:
    async with stdio_client(server(login)) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        me = await call(s, "whoami")
        check(me.get("awaiting_review") == 0, "whoami shows a reviewer what waits for review")


def main() -> None:
    subprocess.run(["dropdb", "--if-exists", "--force", DB], check=True)
    install.install(DB, ["validator-shacl", "recall-bm25"])
    with connect(url=f"dbname={DB}") as su:
        su.execute(f"do $$ begin if not exists (select 1 from pg_roles where rolname = '{ROLE}') then "
                   f"create role {ROLE} login password '{AGENT_PASSWORD}'; end if; end $$")
        su.execute(f"grant kk_agent to {ROLE}")
        for role, member_of in (("t_mcp_switcher", "kkm_validator"), ("t_mcp_reviewer", "kk_reviewer")):
            su.execute(f"do $$ begin if not exists (select 1 from pg_roles where rolname = '{role}') then "
                       f"create role {role} login password '{role}'; end if; end $$")
            su.execute(f"grant {member_of} to {role}")
        su.execute("set role kk_owner")
        su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, %s, 'software', 'MCP test agent'),"
                   " ('urn:kk:agent:test-mcp-switcher', 't_mcp_switcher', 'software', 'switcher'),"
                   " ('urn:kk:agent:test-mcp-reviewer', 't_mcp_reviewer', 'person', 'reviewer')"
                   " on conflict do nothing", (AGENT, ROLE))
    asyncio.run(agent_session(f"dbname={DB} user={ROLE} password={AGENT_PASSWORD}"))
    superuser = f"dbname={DB} user={os.environ.get('PGUSER', 'postgres')}" + (
        f" password={os.environ['PGPASSWORD']}" if os.environ.get("PGPASSWORD") else "")
    asyncio.run(refused(superuser, "a superuser login"))
    asyncio.run(refused(f"dbname={DB} user=t_mcp_switcher password=t_mcp_switcher",
                        "a login that holds another agent's role"))
    asyncio.run(reviewer_session(f"dbname={DB} user=t_mcp_reviewer password=t_mcp_reviewer"))
    subprocess.run(["dropdb", "--force", DB], check=True)
    print("ALL MCP TESTS PASSED")


if __name__ == "__main__":
    main()
