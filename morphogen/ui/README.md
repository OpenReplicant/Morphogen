# Morphogen's UI (T21, R5-36)

An overview of what Morphogen is made of (every slot of the kernel and of Morphogen, the providers that fill each, the
default and where it is written, how a provider is swapped; the vocabularies; what waits, open questions and drift,
R5-50), the review lane, the loop (each plan with who decided it, the run that carried it out and the verifier's
verdict) and the managed systems, in a browser. The page is an MCP client of kernel-mcp: every
call carries the signed-in person's own token, so the record decides what they see and what they may approve.

```sh
# once per person (the password is read from stdin, never an argument)
PGHOST=... PGUSER=<superuser> python3 morphogen/ui/people.py add DB alice

# the server: kernel-mcp over HTTP at /mcp, the page at /ui/, sign-in at /ui/login
DATABASE_URL="host=... dbname=DB user=kk_authenticator password=..." KK_JWT_SECRET=<32+ characters> \
  python3 morphogen/ui/serve.py            # http://localhost:8000/ui/
```

kk_authenticator's password is set at deploy time (`alter role kk_authenticator password ...`). Serve it behind
HTTPS (Caddy, D-74) anywhere but localhost. The overview reads the self-encoder's claims: `local.py up` records them;
elsewhere run `python -m self_encoder scan --distribution morphogen/distribution.yaml --providers morphogen/modules`
(kernel/providers/self-encoder) once. The test: `morphogen/tests/test_ui.py` (headless Chromium).
