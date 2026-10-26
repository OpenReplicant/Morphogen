# Morphogen on your own machine

Two ways, the same Morphogen:

- **In a container** (below): one image with everything inside, run by rootless Podman or Docker. Nothing to
  install but the container engine, and Claude Code runs inside as a user of its own.
- **On the machine itself** ([further down](#on-the-machine-itself)): `morphogen/deploy/local.py` runs each part
  as a process of yours. Everything it keeps lives in `~/.local/state/morphogen` (or `MORPHOGEN_HOME`).

## In a container

You need Podman (rootless, recommended) or Docker, and a checkout of this repository to build the image from.

```sh
podman build -f morphogen/deploy/container/Containerfile -t morphogen:dev .    # or docker build; a few minutes
```

Every download in the build is pinned: the base image by digest, Debian packages by a snapshot date, Python
packages by version and hash (`requirements.lock`, every package), gitleaks, the Docker CLI, Compose and Claude
Code by sha256 (`downloads.txt`, amd64 and arm64). Behind a proxy that re-signs TLS, add
`--secret id=ca,src=<its CA bundle>`.

Run it with three volumes (the instance, the record, the agent's home) and the container engine's socket (so
Morphogen can start the systems you approve):

```sh
# rootless Podman (systemctl --user enable --now podman.socket, once)
podman run -d --init --name morphogen -p 127.0.0.1:8470:8470 \
  -v morphogen:/var/lib/morphogen -v morphogen-db:/var/lib/postgresql/data -v morphogen-agent:/home/agent \
  -v $XDG_RUNTIME_DIR/podman/podman.sock:/run/morphogen-socket/docker.sock morphogen:dev

# Docker
docker run -d --init --name morphogen -p 127.0.0.1:8470:8470 \
  -v morphogen:/var/lib/morphogen -v morphogen-db:/var/lib/postgresql/data -v morphogen-agent:/home/agent \
  -v /var/run/docker.sock:/run/morphogen-socket/docker.sock morphogen:dev
```

Mount the socket at exactly `/run/morphogen-socket/docker.sock` and nowhere else: that directory is root's alone
inside the image, and Morphogen refuses to start if it is not, or if a socket is mounted anywhere else too (it
checks mounted files, not what a mounted folder holds: do not mount the folder a socket lives in). Without a socket, the record and the UI run and approved systems are
committed but not started. Add `-e MORPHOGEN_OPERATOR_NAME=... -e MORPHOGEN_OPERATOR_EMAIL=...` to name yourself
in the intent repository's first commit.

**The socket is the strongest thing you hand over.** Docker's socket is root on your machine to whoever uses it;
rootless Podman's is your own user's. Inside the image only the compose runner (as root in the container) can
reach it, and it runs only committed compose files a person approved, by content, that pass its allow list (images pinned by digest, ports on
127.0.0.1, no host volumes). Prefer rootless Podman.

Then, from your machine:

```sh
podman exec -it morphogen morphogen person alice     # you, as a person who reviews; open http://127.0.0.1:8470/ui/
podman exec -it morphogen morphogen login            # Claude Code's sign-in, once (it shows a code to paste)
podman exec -it morphogen morphogen claude interviewer
```

The last line starts Claude Code inside the container as the user `agent`, with the interviewer's own login to
the record over MCP and the interview skill (`/interview`) in its working folder. Record a conversation from your
machine with `podman exec -i morphogen morphogen record - --source shop < shop.jsonl`, and propose with
`podman exec morphogen morphogen propose shop`; the steps are the same as [below](#describe-a-system-and-have-morphogen-run-it).
`morphogen status` shows what runs; the logs are in `/var/lib/morphogen/logs`. `podman stop morphogen` stops
everything cleanly (Postgres included); the volumes keep the record, the instance and the agent's sign-in.

### How Claude Code signs in

| Way | How | What Claude Code inside can reach |
| --- | --- | --- |
| In the container (default) | `morphogen login`, once, and again when the login expires; kept in the `morphogen-agent` volume | its own login, nothing of yours |
| Copied, read-only | add `-v ~/.claude:/run/morphogen-claude/host:ro` | your login alone: at each `morphogen claude` it is copied from `.credentials.json` into the agent's config. Your settings, hooks, history and other projects stay out of reach, and nothing is written back. On macOS the login is in the Keychain, not in `~/.claude`, so use `morphogen login` there |
| Shared, writable | add `-v ~/.claude:/home/agent/.claude -e MORPHOGEN_CLAUDE_SHARED=1` (rootless Podman also `--userns=keep-id:uid=10002,gid=10002`) | all of your `~/.claude`, as it is: the user `agent` takes the folder's uid and gid, so Claude Code inside reads and refreshes your login as yours does. It can also read your history and write your settings, **hooks included, which your own Claude Code then runs on your machine, outside the container**. Only for a `~/.claude` you would hand to the agent anyway. Without the variable the mount is refused, and so is a folder showing as a system uid or another user's inside |

In the copied way the agent holds your full login, refresh token included, until you revoke it; the host's copy
replaces the agent's only when it is newer, so a login Claude Code refreshed inside is not overwritten by an older
one. If the two drift apart, run `morphogen login`. A long-lived token from `claude setup-token`,
narrower still (model requests only), is planned (docs/decisions.md R5-O10).

### Which models Claude Code uses

Claude Code's own settings choose the endpoint and the models, and Morphogen passes them on to Claude Code alone
(on the machine, from your environment; in the container, from `-e` on `run` or on `exec`): `ANTHROPIC_BASE_URL`
(a gateway such as LiteLLM, which can front other providers' and local models), `ANTHROPIC_AUTH_TOKEN` or
`ANTHROPIC_API_KEY` (its key), `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`,
`ANTHROPIC_DEFAULT_HAIKU_MODEL` (also used for background work), `CLAUDE_CODE_SUBAGENT_MODEL` and
`CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC`. A key given with `-e` on `run` shows in `docker inspect` to whoever
can use the engine; given on `exec`, it lasts for that one Claude Code. Model selection for Morphogen as a whole is
proposed in docs/decisions.md R5-O11.

### What it trusts, in a container

Three users, so what one holds the others cannot read:

| User | Runs | Holds |
| --- | --- | --- |
| `morphogen` | Postgres, the services, the UI | the instance's secrets (`/var/lib/morphogen`, 0700) |
| `agent` | Claude Code and the MCP server it starts | its Claude Code login and its own login to the record (`/home/agent`, 0700) |
| root (in the container) | the compose runner, and copying your login in | the container socket and a read-only `~/.claude` (each in a folder only root enters) |

So Claude Code, which runs commands, can read neither the superuser's password nor the UI's signing secret nor a
service's environment, and cannot use the socket: it reaches the record only as its agent login, which proposes
and never reviews. Every agent runs as the one user `agent`, so `morphogen claude NAME` revokes every other
agent's login before it starts: one agent at a time. The services in turn cannot read its Claude Code login. The
compose runner reads the intent repository, which every process of `morphogen` can write, so it does not trust who
committed a file: it runs one only when a person approved that file, as the plan showed it to them (T26), so an
agent that commits a compose file through its own login gets it refused. This guards against agents, not against
the user `morphogen` itself: a process running as `morphogen` can read the record's superuser password, so it could
forge a person's decision. The compose runner takes nothing but its login from `morphogen` (its code and role are
root's own). `morphogen/tests/test_container.py` checks each of these.

## On the machine itself

### What you need

- Docker (the record runs in a Postgres container, and described systems run as compose projects)
- git, and `psql` (the Postgres client: `apt-get install postgresql-client`, or `brew install libpq`)
- Python 3.12+ with Morphogen's requirements:

  ```sh
  python3 -m venv .venv && . .venv/bin/activate
  pip install -r kernel/contract/requirements.txt -r kernel/providers/kernel-mcp/requirements.txt \
              -r morphogen/modules/observer-otel/requirements.txt -r morphogen/modules/registry-lookup/requirements.txt
  ```

- gitleaks 8.30.1 on PATH, for the design agent's intake filter (docs/DEVELOPING.md, section 1). Without it the
  design agent refuses to propose: the filter fails closed.
- For describing a system through an agent: Claude Code.

### Bring it up

```sh
python3 morphogen/deploy/local.py up             # first time: pulls Postgres, installs the record (a minute)
python3 morphogen/deploy/local.py person alice   # you, as a person who reviews; asks for a password (12+ characters)
```

Open http://127.0.0.1:8470/ui/ and sign in. The Review tab is empty until something is proposed; Loop shows what
the services record; Systems shows the systems Morphogen knows.

`up` starts:

| Process | What it does |
| --- | --- |
| `reconcile` | runs the services named in `intent/environments/local/` (validator, belief, truth maintenance, quote verifier, recall index, analyser, planner, intent actuator, prediction verifier, gap finder) and restarts one when its intent file changes |
| `observer-otel` | records the services' own telemetry (feed lag, step time) as observations, so Morphogen watches itself |
| `compose` | the runtime (runtime-compose; runtime-quadlet with `MORPHOGEN_RUNTIME=quadlet`, Podman 5.6+ and systemd on this machine): runs every system under `intent/systems/` as committed, when an approved plan step names the file, including one approved later |
| `ui` | the review and loop UI, and kernel-mcp over HTTP for signed-in people |

`status` shows what runs and where the logs are; `down` stops the processes (`down --db` stops Postgres too; the
data stays in the Docker volume `morphogen-pgdata`).

### Describe a system and have Morphogen run it

1. **Give your agent a login of its own.**

   ```sh
   python3 morphogen/deploy/local.py agent interviewer
   ```

   It prints an MCP config. Start Claude Code with it (`claude --mcp-config <file>`): the agent then reads and
   proposes through the record as `urn:kk:agent:interviewer`, and can never approve anything. Or let `local.py`
   start it: `local.py claude interviewer` makes the login and starts Claude Code with the config, signed in as
   you are.

2. **Record the conversation.** Talk the system through, then save it as JSON lines, one message each:

   ```json
   {"id": "1", "conversation": "shop-intake", "author": "interviewer", "kind": "agent", "time": "2026-11-01T09:00:00Z", "text": "What system would you like Morphogen to run?"}
   {"id": "2", "conversation": "shop-intake", "author": "Alice", "time": "2026-11-01T09:00:30Z", "text": "A small shop: a storefront that calls a cart service, and the cart keeps carts in Redis."}
   ```

   ```sh
   python3 morphogen/deploy/local.py record shop.jsonl --source shop
   ```

   Each message becomes a note (`urn:kk:message:shop:shop-intake:<id>`) the agent quotes.

3. **Let the agent describe it.** Ask Claude Code to follow `morphogen/skills/interview/SKILL.md` for the system
   `shop`. It records services, images, settings and limits, each quoting one of your messages. The gap finder
   then lists what is missing as questions (the UI's Loop tab shows them): a service with no image, an image not
   pinned by digest (`docker buildx imagetools inspect <image>` gives the digest), a service connected to nothing,
   an entry point with no documented limit. Answer them, add the answers to the conversation, record it again
   and let the agent record what they say.

4. **Propose.** With no question open:

   ```sh
   python3 morphogen/deploy/local.py propose shop
   ```

   It refuses, with the reason, while a question is open, while the description conflicts, while a quote was
   refuted, when the file would carry a secret, or when the compose runner would not run it (an image not pinned
   by digest, a port off 127.0.0.1, a volume, ...). Otherwise the compose file waits in the UI's Review tab.

5. **Approve it in the UI.** The intent actuator commits the file to `intent/systems/shop/compose.yaml`, and the
   compose runner starts it as the project `kk-shop` (`docker compose -p kk-shop ps`). What runs is exactly the
   text you approved: the actuator writes it only if the record still renders that text.

### What it trusts

Each service connects to the record as a login of its own that may act as that service only, so a mistaken
service cannot approve a plan, act as a person or as another service. The UI's login may act as any signed-in
person: it is the one process trusted that far. Every process still runs as you, so this guards against mistakes,
not against hostile code on your machine; Morphogen never starts model-written code here. Claude Code runs as you
too, so a command it runs could read `MORPHOGEN_HOME`; in the container it runs as a user of its own and cannot.

### What is not here yet

- Watching a described system's own metrics: start `observer-prometheus` with `KK_PROM_TARGETS` pointing at its
  ports (`morphogen/modules/observer-prometheus`), and document a limit, and the analyser and planner follow it.
- Model-written code (the builder and the sandbox): it needs run users and nftables (docs/DEVELOPING.md).
- HTTPS for the UI: it listens on 127.0.0.1 only (in the container, on the port published on 127.0.0.1); put
  Caddy in front before exposing it.
- The interviewer asking its questions live: today the conversation is recorded from a file.
