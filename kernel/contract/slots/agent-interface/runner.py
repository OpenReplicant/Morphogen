"""The agent-interface slot's own runner (set.yaml `runner:`): talks MCP over stdio to one provider's service, started
with an agent's own login, and judges what it answers. Prints "ok: <case id>" per passing case. Never imports the
provider.

  python3 runner.py <provider directory>
"""
import asyncio
import json
import os
import sys
from pathlib import Path

import yaml
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from harness import KERNEL, Record, check, package  # noqa: E402

C = "urn:kk:contract:agent-interface/"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
AGENT = "urn:kk:agent:contract-mcp"
TOOLS = set(yaml.safe_load((HERE / "set.yaml").read_text())["tools"])


def server(provider: Path, login: str) -> StdioServerParameters:
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "PGHOST", "PGPORT", "LANG")}
    env.update(PYTHONPATH=os.pathsep.join([str(KERNEL / "src"), str(provider)]), KK_DATABASE_URL=login)
    return StdioServerParameters(command=sys.executable, args=["-m", package(provider)], env=env, cwd=str(provider))


async def call(s: ClientSession, tool: str, args: dict | None = None):
    res = await s.call_tool(tool, args or {})
    if res.is_error:
        return {"error": res.content[0].text if res.content else "error"}
    sc = res.structured_content
    if isinstance(sc, dict):
        return sc.get("result", sc)
    return json.loads(res.content[0].text) if res.content else None


def fact(s, v, derived=None):
    op = {"op": "add_claim", "subject": s, "predicate": LABEL, "object": {"value": {"@value": v}}}
    if derived:
        return {**op, "evidence_type": "inferred", "derived_from": derived}
    return {**op, "evidence_type": "testimony", "references": [{"source_uri": f"urn:test:{s}"}]}


async def session(provider: Path, rec: Record, login: str) -> bool:
    ok = True
    async with stdio_client(server(provider, login)) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        names = {t.name for t in (await s.list_tools()).tools}
        ok &= check(TOOLS <= names, C + "tools", f"missing {sorted(TOOLS - names)}")
        me = await call(s, "whoami")
        ok &= check(isinstance(me, dict) and me.get("agent") == AGENT, C + "whoami", str(me))

        found = await call(s, "search", {"text": "centrifugal pump hall three", "limit": 10})
        listed = await call(s, "query_claims", {"subject": "urn:x:pump"})
        ok &= check(isinstance(found, list) and found and isinstance(listed, list) and listed
                    and all("id" in c and "belief" in c for c in found + listed)
                    and rec.ids["pump"] in {str(c["id"]) for c in found}, C + "cites", f"{found!s:.300} {listed!s:.300}")
        ex = await call(s, "explain", {"claim_id": rec.ids["derived"]})
        text = json.dumps(ex, default=str)
        ok &= check(isinstance(ex, dict) and "error" not in ex and rec.ids["pump"] in text and "derived" in text,
                    C + "explain", text[:400])
        hidden = rec.ids["hidden"]
        seen = await call(s, "search", {"text": "secret centrifugal pump hall three", "limit": 50})
        by_subject = await call(s, "query_claims", {"subject": "urn:x:hidden"})
        ex_hidden = await call(s, "explain", {"claim_id": hidden})
        ok &= check(hidden not in json.dumps(seen, default=str) and not by_subject
                    and (not isinstance(ex_hidden, dict) or "error" in ex_hidden or not ex_hidden.get("claim")),
                    C + "clearance", f"{seen!s:.200} {by_subject!s:.200} {ex_hidden!s:.200}")

        run_id = await call(s, "start_run", {"module": "urn:kk:module:contract-mcp"})
        got = await call(s, "submit_change_set", {"change_set": {
            "idempotency_key": "contract:mcp:1", "attributed_to": AGENT, "generated_by": run_id,
            "target_scope": "urn:kk:scope:default", "ops": [fact("urn:x:via-mcp", "written through the interface")]}})
        status = got.get("status") if isinstance(got, dict) else None
        rec.validate()
        await call(s, "finish_run", {"run_id": run_id})
        after = await call(s, "get_change_set", {"change_set_id": str(got.get("id"))}) if isinstance(got, dict) else None
        row = rec.rows("select attributed_to, generated_by::text from kernel.claim where subject = 'urn:x:via-mcp'")
        ok &= check(status == "submitted" and isinstance(after, dict) and after.get("status") == "applied"
                    and row == [{"attributed_to": AGENT, "generated_by": run_id}], C + "write-path", f"{got} {after!s:.200} {row}")
        spoof = await call(s, "submit_change_set", {"change_set": {
            "idempotency_key": "contract:mcp:spoof", "attributed_to": "urn:kk:agent:contract-other", "generated_by": run_id,
            "target_scope": "urn:kk:scope:default", "ops": [fact("urn:x:spoof", "as someone else")]}})
        rec.validate()
        ok &= check(not rec.rows("select 1 from kernel.claim where subject = 'urn:x:spoof'")
                    and isinstance(spoof, dict) and "error" in spoof, C + "attribution", str(spoof))
    return ok


async def refused(provider: Path, login: str) -> bool:
    try:
        async with stdio_client(server(provider, login)) as (r, w), ClientSession(r, w) as s:
            await s.initialize()
            me = await call(s, "whoami")
            claims = await call(s, "query_claims", {"limit": 1})
            return isinstance(me, dict) and "error" in me and isinstance(claims, dict) and "error" in claims
    except Exception:                         # the server would not start with that login: refused too
        return True


def main(provider: Path) -> int:
    rec = Record("kkc_mcp", [provider])
    try:
        login = rec.agent_login("kkc_mcp_agent", AGENT)
        writer = rec.agent("kkc_mcp_writer", "urn:kk:agent:contract-other")
        secret = rec.scope("urn:kk:scope:contract-secret", readers=(writer,))
        rec.submit(writer, [fact("urn:x:pump", "the centrifugal pump in hall three")])
        rec.ids = {"pump": rec.claim("urn:x:pump")}
        rec.submit(writer, [fact("urn:x:derived", "derived from the pump", [rec.ids["pump"]])])
        rec.submit(writer, [fact("urn:x:hidden", "secret centrifugal pump in hall three")], scope=secret)
        rec.ids |= {"derived": rec.claim("urn:x:derived"), "hidden": rec.claim("urn:x:hidden")}
        ok = asyncio.run(session(provider, rec, login))
        su = " ".join(f"{k}={v}" for k, v in (("dbname", rec.db), ("user", os.environ.get("PGUSER", "postgres")),
                                               ("password", os.environ.get("PGPASSWORD")), ("host", os.environ.get("PGHOST")),
                                               ("port", os.environ.get("PGPORT"))) if v)
        ok &= check(asyncio.run(refused(provider, su)), C + "no-switching-login", "a superuser login was served")
        return 0 if ok else 1
    finally:
        rec.drop()


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
