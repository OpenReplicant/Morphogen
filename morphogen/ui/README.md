# Morphogen's UI (T21, R5-36)

The review lane, the loop and the managed systems, in a browser. The page is an MCP client of kernel-mcp: every
call carries the signed-in person's own token, so the record decides what they see and what they may approve.

```sh
# once per person (the password is read from stdin, never an argument)
PGHOST=... PGUSER=<superuser> python3 morphogen/ui/people.py add DB alice

# the server: kernel-mcp over HTTP at /mcp, the page at /ui/, sign-in at /ui/login
DATABASE_URL="host=... dbname=DB user=kk_authenticator password=..." KK_JWT_SECRET=<32+ characters> \
  python3 morphogen/ui/serve.py            # http://localhost:8000/ui/
```

kk_authenticator's password is set at deploy time (`alter role kk_authenticator password ...`). Serve it behind
HTTPS (Caddy, D-74) anywhere but localhost. The test: `morphogen/tests/test_ui.py` (headless Chromium).
