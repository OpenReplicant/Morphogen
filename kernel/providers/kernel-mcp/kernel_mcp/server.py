"""Agent-facing MCP tools over the kernel's api schema, on the MCP Python SDK v2 (MCPServer).

Talks to Postgres directly. Every tool call runs in its own transaction as the caller's database
role, so row-level security, write clearance and attribution are enforced by Postgres per agent;
this server decides nothing. Who the caller is:
  - stdio (one harness, one agent): KK_DATABASE_URL (or DATABASE_URL, or the file KK_LOGIN_FILE names) is the agent's
    own login (e.g. agent_claude_code).
    The server never switches roles in this mode, and refuses a login that could (kk_authenticator,
    superusers): whoever holds such a password could act as anyone, the owner included.
  - http (shared server): DATABASE_URL is kk_authenticator, which only this server holds; each
    request's bearer JWT (signed with KK_JWT_SECRET, `role` claim; minted by `kk token ROLE`)
    names the role it switches to (SET LOCAL ROLE). A request without a valid token is refused.
Every claim returned carries its id and belief, so answers can cite them (invariant 6).

Ported from rebuild 4 modules/kernel-mcp: the operator tools, unchanged. Not ported (R5-12): the memory
profile (remember, recall briefings, changes_since) and the briefing, which serve agent memory, a use no
distribution has yet; dense recall (not ported yet; re-ranking is, opt-in in kk.recall, T16); the harness hooks
(harness-adapter slot).
"""
from __future__ import annotations

import asyncio

import os
from contextlib import asynccontextmanager
from typing import Any

import jwt
import psycopg
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from psycopg import sql
from psycopg.types.json import Jsonb

from kk import recall

PREFIXES = {  # same as kernel.prefix (kernel/providers/record-postgres/schema/002_bootstrap.sql)
    "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#", "rdfs": "http://www.w3.org/2000/01/rdf-schema#",
    "owl": "http://www.w3.org/2002/07/owl#", "xsd": "http://www.w3.org/2001/XMLSchema#",
    "skos": "http://www.w3.org/2004/02/skos/core#", "dcterms": "http://purl.org/dc/terms/",
    "prov": "http://www.w3.org/ns/prov#", "pplan": "http://purl.org/net/p-plan#", "oa": "http://www.w3.org/ns/oa#",
    "sh": "http://www.w3.org/ns/shacl#", "td": "https://www.w3.org/2019/wot/td#",
    "kk": "https://w3id.org/knowledge-kernel/ns#", "kkt": "https://w3id.org/knowledge-kernel/tosca#",
    "kkp": "https://w3id.org/knowledge-kernel/profile#",
}
CLAIM_COLUMNS = ("id, subject, predicate, object_entity, object_value, qualifiers, scope, evidence_type, "
                 "attributed_to, status, belief, valid_from, valid_to")
RDF_TYPE = PREFIXES["rdf"] + "type"
REQUIRE_TOKEN = False  # set by the http entrypoint

mcp = MCPServer(
    "knowledge-kernel",
    instructions="Knowledge Kernel: a governed record. search(text) and query_claims find claims; explain(id) "
                 "shows where one came from. You write only by submit_change_set, as yourself, within a run "
                 "you started; validation, the lane policy and people decide what is applied. Cite claim ids "
                 "and their belief in every answer.",
)


class KernelError(ToolError):
    """An anticipated failure (no identity, the kernel refused): the agent sees the message."""


def expand(term: str | None) -> str | None:
    if term is None:
        return None
    prefix, sep, local = term.partition(":")
    if sep and prefix in PREFIXES and not local.startswith("//"):
        return PREFIXES[prefix] + local
    return term


def caller(ctx: Context | None) -> tuple[str | None, str]:
    """The role to switch to (http; None when the login itself is the caller, stdio) and the caller's
    profile (rebuild 4's `profile` claim; only `operator` is served here)."""
    if not REQUIRE_TOKEN:
        return None, "operator"
    auth = ((ctx.headers if ctx else None) or {}).get("authorization", "")
    if not auth.lower().startswith("bearer ") or not auth[7:].strip():
        raise KernelError("no bearer token: send 'Authorization: Bearer <your agent JWT>'")
    try:
        claims = jwt.decode(auth[7:].strip(), os.environ["KK_JWT_SECRET"], algorithms=["HS256"])
    except jwt.PyJWTError as e:
        raise KernelError(f"invalid token: {e}") from None
    if not claims.get("role"):
        raise KernelError("token has no role claim")
    return claims["role"], claims.get("profile") or "operator"


def database_url() -> str:
    """The agent's login: KK_DATABASE_URL from the file KK_LOGIN_FILE names (written by `kk up`, so the
    secret stays out of the project's files), else KK_DATABASE_URL, else DATABASE_URL (KK_ first, so a
    harness's own DATABASE_URL does not collide)."""
    if os.environ.get("KK_LOGIN_FILE"):
        for line in open(os.path.expanduser(os.environ["KK_LOGIN_FILE"])):
            key, _, value = line.strip().partition("=")
            if key == "KK_DATABASE_URL" and value:
                return value
        raise KernelError(f"no KK_DATABASE_URL in {os.environ['KK_LOGIN_FILE']}")
    url = os.environ.get("KK_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise KernelError("set KK_DATABASE_URL (or DATABASE_URL) to the agent's own login")
    return url


# A login that could act as someone else: a superuser, one that can create roles or bypass row-level
# security, or a member of another agent's role (kk_authenticator is one: it holds every kkm_* role).
# Rebuild 4 checked only the first and kk_authenticator by name.
SWITCHING_LOGIN = """select r.rolsuper or r.rolcreaterole or r.rolbypassrls or exists (
                       select 1 from kernel.agent a
                       where a.db_role <> current_user and pg_has_role(current_user, a.db_role, 'member'))
                     from pg_roles r where r.rolname = current_user"""


@asynccontextmanager
async def connection(ctx: Context):
    """A connection in one transaction as the caller (http: SET LOCAL ROLE to the token's role)."""
    role = caller(ctx)[0]
    try:
        async with await psycopg.AsyncConnection.connect(database_url()) as conn:
            async with conn.transaction():
                if role:
                    await conn.execute(sql.SQL("set local role {}").format(sql.Identifier(role)))
                elif (await (await conn.execute(SWITCHING_LOGIN)).fetchone())[0]:
                    raise KernelError("stdio needs the agent's own login in DATABASE_URL, not one that can "
                                      "act as another agent (kk_authenticator, a superuser, or a member of "
                                      "another agent's role)")
                yield conn
    except psycopg.Error as e:
        raise KernelError(f"kernel refused: {(e.diag.message_primary or str(e))[:500]}") from None


async def one(conn, statement: str, params: tuple | dict = ()) -> Any:
    """The first column of the first row of one statement on `conn`."""
    row = await (await conn.execute(statement, params)).fetchone()
    return row[0] if row else None


async def query(ctx: Context, statement: str, params: tuple | dict = ()) -> Any:
    """Run one statement as the caller; returns the first column of the first row."""
    async with connection(ctx) as conn:
        return await one(conn, statement, params)


def rows(select: str) -> str:
    """Wrap a select so Postgres returns its rows as one JSON array."""
    return f"select coalesce(jsonb_agg(to_jsonb(r)), '[]'::jsonb) from ({select}) r"


# ------------------------------------------------------------------ reading
@mcp.tool()
async def query_claims(ctx: Context, subject: str | None = None, predicate: str | None = None,
                       object_entity: str | None = None, scope: str | None = None,
                       include_deprecated: bool = False, limit: int = 100) -> list[dict]:
    """Claims matching all given filters (IRIs or CURIEs such as rdfs:label). Each has id, status and belief."""
    return await query(ctx, rows(
        f"select {CLAIM_COLUMNS} from api.claims"
        " where (%(s)s::text is null or subject = %(s)s) and (%(p)s::text is null or predicate = %(p)s)"
        "   and (%(o)s::text is null or object_entity = %(o)s) and (%(sc)s::text is null or scope = %(sc)s)"
        "   and (%(dep)s or status <> 'deprecated')"
        " order by subject, predicate limit %(n)s"),
        {"s": expand(subject), "p": expand(predicate), "o": expand(object_entity), "sc": expand(scope),
         "dep": include_deprecated, "n": max(1, min(limit, 1000))})


@mcp.tool()
async def get_entity(ctx: Context, iri: str) -> dict:
    """The entity card: current claims about the entity, and claims that point at it."""
    iri = expand(iri)
    return await query(ctx, f"""select jsonb_build_object('iri', %(i)s::text,
        'claims', ({rows(f"select {CLAIM_COLUMNS} from api.claims where subject = %(i)s and status <> 'deprecated' order by predicate limit 500")}),
        'referenced_by', ({rows(f"select {CLAIM_COLUMNS} from api.claims where object_entity = %(i)s and status <> 'deprecated' order by predicate limit 200")}))""",
        {"i": iri})


@mcp.tool()
async def search(ctx: Context, text: str, limit: int = 20) -> list[dict]:
    """Claims ranked by relevance to the text (any words; BM25 when the recall index is installed, else
    full-text search, then belief), or by substring on labels and IRIs when no word matches. Each has id,
    status, belief, rank."""
    indexed = bool(await query(ctx, recall.INSTALLED) and await query(ctx, recall.READY))
    rerank = indexed and recall.reranker() is not None     # KK_RERANK=1 and the model cached (kk.recall)
    rows = await query(ctx, recall.ranked(indexed), recall.params(text, max(limit, recall.POOL) if rerank else limit))
    if rows and rerank:
        subjects = list(dict.fromkeys(c.get("subject") or "" for c in rows[:recall.POOL]))
        texts = await query(ctx, recall.TEXTS, {"subjects": subjects})
        return await asyncio.to_thread(recall.rerank, text, rows, limit, texts)
    return (rows or await query(ctx, recall.SUBSTRING, recall.params(text, limit)))[:limit]


@mcp.tool()
async def explain(ctx: Context, claim_id: str) -> dict:
    """Where a claim came from: sources and quotes, derivations, uses, status history, beliefs, verifications,
    run. claim_id: a claim id, or its first characters (at least four)."""
    async with connection(ctx) as conn:
        return await one(conn, "select api.explain(%s::uuid)", (await resolve(conn, claim_id),))


async def resolve(conn, h: str) -> str:
    """A claim id from a prefix of at least four hex characters (#1a2b3c4d) or a full id (rebuild 4 memory.py)."""
    h = h.strip().lstrip("#").lower()
    hexes = h.replace("-", "")
    if len(hexes) < 4 or any(ch not in "0123456789abcdef" for ch in hexes) or len(hexes) > 32:
        raise KernelError(f"not a claim id: {h!r}")
    lo, hi = (hexes + pad * (32 - len(hexes)) for pad in "0f")
    uuid = lambda x: f"{x[:8]}-{x[8:12]}-{x[12:16]}-{x[16:20]}-{x[20:]}"   # noqa: E731
    found = await one(conn, "select coalesce(array_agg(id::text), '{}') from (select id from api.claims"
                            " where id between %s::uuid and %s::uuid limit 2) c", (uuid(lo), uuid(hi)))
    if not found:
        raise KernelError(f"no claim you can see has the id #{h}")
    if len(found) > 1:
        raise KernelError(f"#{h} matches more than one claim; give more characters")
    return found[0]


async def _typed(ctx: Context, cls: str, props: list[str]) -> list[dict]:
    return await query(ctx, f"""
        select coalesce(jsonb_agg(jsonb_build_object(
                 'iri', t.subject, 'type_claim', jsonb_build_object('id', t.id, 'belief', t.belief),
                 'claims', ({rows(f"select {CLAIM_COLUMNS} from api.claims f where f.subject = t.subject and f.predicate = any(%(props)s) and f.status <> 'deprecated'")}))
               order by t.subject), '[]'::jsonb)
        from api.claims t where t.predicate = %(type)s and t.object_entity = %(cls)s and t.status <> 'deprecated'""",
        {"type": RDF_TYPE, "cls": expand(cls), "props": [expand(p) for p in props]})


@mcp.tool()
async def list_slots(ctx: Context) -> list[dict]:
    """The slot catalog as the kernel knows it: each slot with its contract and cardinality claims."""
    return await _typed(ctx, "kk:Slot", ["rdfs:label", "kk:slotContract", "kk:cardinality"])


@mcp.tool()
async def list_modules(ctx: Context) -> list[dict]:
    """Modules in the self-model: label, version, kind, the slots they fill and the agent they run as."""
    return await _typed(ctx, "kk:Module", ["rdfs:label", "owl:versionInfo", "kk:moduleKind", "kk:fills", "kk:runsAs",
                                           "kk:protected"])


# ------------------------------------------------------------------ writing
@mcp.tool()
async def start_run(ctx: Context, module: str | None = None, plan_step: str | None = None,
                    info: dict | None = None) -> str:
    """Start a run under your own identity; every change set names the run that produced it."""
    return str(await query(ctx, "select api.start_run(%s, %s, '[]'::jsonb, %s)",
                           (module, plan_step, Jsonb(info or {}))))


@mcp.tool()
async def submit_change_set(ctx: Context, change_set: dict) -> dict:
    """Submit a change set (kernel/schemas/change_set.schema.json). Returns {id, status, lane}.
    attributed_to must be your own agent IRI and generated_by one of your running runs."""
    return await query(ctx, "select api.submit_change_set(%s)", (Jsonb(change_set),))


@mcp.tool()
async def get_change_set(ctx: Context, change_set_id: str) -> dict:
    """Status of one of your change sets, with the validation report when it is invalid."""
    found = await query(ctx, "select to_jsonb(c) from api.change_sets c where id = %s::uuid", (change_set_id,))
    if not found:
        raise KernelError(f"change set {change_set_id} not found among those you can see")
    return found


@mcp.tool()
async def list_runs(ctx: Context, plan_step: str | None = None, used: str | None = None, module: str | None = None,
                    limit: int = 50) -> list[dict]:
    """Runs (prov:Activity), newest first: who ran what, for which plan step, using which claims, with
    status, times and outputs. Filter by plan step IRI, a claim id or IRI the run used, or module IRI.
    An actuator's runs are how it records what it did (it never writes claims)."""
    return await query(ctx, rows(
        "select id, agent, module, plan_step, status, started_at, ended_at, used, cost as outputs, info from kernel.run"
        " where (%(ps)s::text is null or plan_step = %(ps)s) and (%(m)s::text is null or module = %(m)s)"
        "   and (%(u)s::text is null or used ? %(u)s)"
        " order by started_at desc limit %(n)s"),
        {"ps": expand(plan_step), "m": expand(module), "u": used, "n": max(1, min(limit, 500))})


@mcp.tool()
async def finish_run(ctx: Context, run_id: str, status: str = "succeeded", cost: dict | None = None) -> str:
    """Finish one of your runs: status succeeded or failed, cost e.g. {"tokens": 1200, "ms": 5300}."""
    await query(ctx, "select api.finish_run(%s::uuid, %s, %s)", (run_id, status, Jsonb(cost or {})))
    return status


# ------------------------------------------------------------------ people and views (the UI uses these too)
@mcp.tool()
async def whoami(ctx: Context) -> dict:
    """Your identity as the kernel sees it: login role, agent IRI, claims you can see, and (reviewers only)
    what waits for review."""
    async with connection(ctx) as conn:
        me = await one(conn, """select jsonb_build_object('role', current_user, 'agent', kernel.my_agent(),
            'claims_visible', (select count(*) from api.claims where status <> 'deprecated'))""")
        # api.review_queue is readable by reviewers only, and Postgres checks a whole statement's
        # privileges before running it, so the count is a second statement (rebuild 4 failed here).
        if await one(conn, "select has_table_privilege('api.review_queue', 'select')"):
            me["awaiting_review"] = await one(conn, "select count(*) from api.review_queue")
        return me


@mcp.tool()
async def list_change_sets(ctx: Context, status: str | None = None, limit: int = 50) -> list[dict]:
    """Change sets you can see (your own; reviewers and validators: all in their cleared scopes), newest first."""
    return await query(ctx, rows(
        "select id, idempotency_key, attributed_to, target_scope, lane, status, submitted_at, validation_report,"
        " jsonb_array_length(ops) as op_count from api.change_sets"
        " where (%(st)s::text is null or status = %(st)s) order by submitted_at desc limit %(n)s"),
        {"st": status, "n": max(1, min(limit, 500))})


@mcp.tool()
async def review_queue(ctx: Context, limit: int = 50) -> list[dict]:
    """Change sets waiting for a person's review in scopes you may review (reviewers only), oldest first."""
    return await query(ctx, rows("select * from api.review_queue order by submitted_at limit %s"),
                       (max(1, min(limit, 200)),))


@mcp.tool()
async def review(ctx: Context, change_set_id: str, approve: bool, note: str | None = None) -> str:
    """Approve or reject a change set in the review lane. People only: the kernel refuses anyone who is
    not a reviewer for its scope, and anyone reviewing their own change set."""
    return await query(ctx, "select api.review(%s::uuid, %s, %s)", (change_set_id, approve, note))


@mcp.tool()
async def graph(ctx: Context, module: str | None = None, slot: str | None = None, root: str | None = None,
                depth: int = 1) -> dict:
    """The claims you can see as a graph (Cytoscape.js elements): nodes are entities, edges are claims with
    id, belief and status. Optional focus: a module, a slot, or a root entity with a depth."""
    from .graph import build, cytoscape, select
    claims = await query(ctx, rows(
        "select id, subject, predicate, object_entity, object_value, status, belief from api.claims"
        " where status <> 'deprecated' and (object_entity is not null or predicate = %s) limit 20000"),
        (PREFIXES["rdfs"] + "label",))
    g = build(claims)
    return cytoscape(g, select(g, expand(module), expand(slot), expand(root), max(1, min(depth, 4))))

