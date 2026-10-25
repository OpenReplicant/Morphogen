"""Morphogen's UI (T21; rebuild 4 kk/ui.py and modules/ui, D-44, D-74): kernel-mcp over HTTP plus these routes.

  python morphogen/ui/serve.py      http://localhost:8000/ui/

  /ui/          the page (web/): an MCP client; every call carries the person's own token, so the store decides
                what they see and what they may approve (R5-05), never the page
  /ui/login     POST {name, password}: a person signs in with their own Postgres login (people.py); Postgres
                checks the password, and the answer is a bearer token for their role, valid SESSION_HOURS (people.py
                remove ends it at once)
  /mcp          kernel-mcp (streamable HTTP), as the token's role

Only the sign-in touches the database outside kernel-mcp, and only as the person. Responses carry a strict
Content-Security-Policy (scripts from this origin only; Alpine.js needs 'unsafe-eval' for its expressions).

Env: DATABASE_URL (kk_authenticator's login: kernel-mcp switches to each token's role), KK_JWT_SECRET (at least
32 characters), KK_LOGIN_URL (where a person's login connects, default DATABASE_URL with their name and
password), PORT (default 8000), KK_UI_HOST (where it listens, default 127.0.0.1; 0.0.0.0 inside a container
whose port is published on 127.0.0.1), KK_MCP_ALLOWED_HOSTS, KK_SITE (kernel-mcp's).
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT / "kernel" / "src"), str(ROOT / "kernel" / "providers" / "kernel-mcp"), str(HERE)]

from people import NAME, role  # noqa: E402

SESSION_HOURS = 8
PERSON = "kk_reviewer"   # people are reviewers (people.py); agents and providers do not sign in here
CSP = ("default-src 'self'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'")
HEADERS = {"content-security-policy": CSP, "x-content-type-options": "nosniff", "referrer-policy": "no-referrer",
           "cache-control": "no-cache"}


def mint(r: str, secret: str, hours: float = SESSION_HOURS) -> str:
    """A bearer token for role `r`, as kernel-mcp verifies them (HS256, `role` claim)."""
    import jwt
    now = int(time.time())
    return jwt.encode({"role": r, "iat": now, "exp": now + int(hours * 3600)}, secret, algorithm="HS256")


# A person's login: a member of kk_reviewer whose agent is a person, that cannot act as anyone else (kernel-mcp's
# SWITCHING_LOGIN: a superuser, a login that creates roles or bypasses row-level security, or a member of another
# agent's role).
PERSON_LOGIN = """select pg_has_role(current_user, %s, 'member')
                    and exists (select 1 from kernel.agent where db_role = current_user and kind = 'person')
                    and not (r.rolsuper or r.rolcreaterole or r.rolbypassrls)
                    and not exists (select 1 from kernel.agent a where a.db_role <> current_user
                                     and pg_has_role(current_user, a.db_role, 'member'))
                  from pg_roles r where r.rolname = current_user"""


async def sign_in(name: str, password: str, url: str) -> str | None:
    """The person's role if Postgres checked their password and the login is a person's (PERSON_LOGIN); else None.
    A connection Postgres let in without asking for the password (trust, peer) is refused: it proves nothing."""
    import psycopg
    from psycopg.conninfo import make_conninfo
    r = role(name)
    try:
        async with await psycopg.AsyncConnection.connect(make_conninfo(url, user=r, password=password),
                                                         connect_timeout=10) as conn:
            if not conn.pgconn.used_password:
                return None
            row = await (await conn.execute(PERSON_LOGIN, (PERSON,))).fetchone()
    except psycopg.Error:
        return None
    return r if row and row[0] else None


class Secure:
    """ASGI wrapper adding the security headers to every response of the wrapped app."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                message = {**message, "headers": [*message.get("headers", []),
                                                  *((k.encode(), v.encode()) for k, v in HEADERS.items())]}
            await send(message)
        await self.app(scope, receive, send_with_headers)


def routes() -> list:
    from starlette.responses import JSONResponse, RedirectResponse
    from starlette.routing import Mount, Route
    from starlette.staticfiles import StaticFiles

    async def home(request):
        return RedirectResponse("/ui/")

    async def login(request):
        try:
            body = await request.json()
            name, password = str(body["name"]), str(body["password"])
        except Exception:
            return JSONResponse({"error": "send {name, password}"}, status_code=400, headers=HEADERS)
        secret = os.environ.get("KK_JWT_SECRET", "")
        url = os.environ.get("KK_LOGIN_URL") or os.environ.get("DATABASE_URL", "")
        if len(secret) < 32 or not url:
            return JSONResponse({"error": "sign-in is not configured"}, status_code=503, headers=HEADERS)
        r = await sign_in(name, password, url) if NAME.fullmatch(name) and password else None
        if not r:
            await asyncio.sleep(1)   # slows guessing; Postgres logs every failed attempt
            return JSONResponse({"error": "name or password not accepted"}, status_code=401, headers=HEADERS)
        return JSONResponse({"token": mint(r, secret), "role": r, "expires": int(time.time()) + SESSION_HOURS * 3600},
                            headers=HEADERS)

    return [Route("/", home), Route("/ui", home), Route("/ui/login", login, methods=["POST"]),
            Mount("/ui", app=Secure(StaticFiles(directory=HERE / "web", html=True)))]


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT / "morphogen" / "src"))
    from morphogen.logins import undumpable
    undumpable()                       # KK_JWT_SECRET signs every person's token: not readable from /proc by other processes
    from kernel_mcp.__main__ import http
    http(host=os.environ.get("KK_UI_HOST", "127.0.0.1"), extra_routes=routes())
