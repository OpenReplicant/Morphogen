# Morphogen on your own machine

One script, `morphogen/deploy/local.py`, brings up the record, the services, the compose runner and the review
UI. Everything it keeps lives in `~/.local/state/morphogen` (or `MORPHOGEN_HOME`), readable by you alone.

## What you need

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

## Bring it up

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
| `compose` | runs every system under `intent/systems/` as committed, including one approved later |
| `ui` | the review and loop UI, and kernel-mcp over HTTP for signed-in people |

`status` shows what runs and where the logs are; `down` stops the processes (`down --db` stops Postgres too; the
data stays in the Docker volume `morphogen-pgdata`).

## Describe a system and have Morphogen run it

1. **Give your agent a login of its own.**

   ```sh
   python3 morphogen/deploy/local.py agent interviewer
   ```

   It prints an MCP config. Start Claude Code with it (`claude --mcp-config <file>`): the agent then reads and
   proposes through the record as `urn:kk:agent:interviewer`, and can never approve anything.

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

## What it trusts

Each service connects to the record as a login of its own that may act as that service only, so a mistaken
service cannot approve a plan, act as a person or as another service. The UI's login may act as any signed-in
person: it is the one process trusted that far. Every process still runs as you, so this guards against mistakes,
not against hostile code on your machine; Morphogen never starts model-written code here.

## What is not here yet

- Watching a described system's own metrics: start `observer-prometheus` with `KK_PROM_TARGETS` pointing at its
  ports (`morphogen/modules/observer-prometheus`), and document a limit, and the analyser and planner follow it.
- Model-written code (the builder and the sandbox): it needs run users and nftables (docs/DEVELOPING.md).
- HTTPS for the UI: it listens on 127.0.0.1 only; put Caddy in front before exposing it.
- The interviewer asking its questions live: today the conversation is recorded from a file.
