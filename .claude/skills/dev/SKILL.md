---
name: dev
description: Set up the environment and run every check for this repo (Postgres for the contract suite, the boundary check). Use at the start of a session and before every commit.
---
# Environment and checks

0. Reference implementation (read-only, for porting): `git clone --depth 1 https://github.com/OpenReplicant/kernel ../kernel-reference`. Port from it; never push to it from this work.
1. Postgres 16+ superuser. If `/usr/lib/postgresql/16/bin` is missing: `apt-get install -y postgresql-16 postgresql-16-pgvector`. Then, in a cloud sandbox:
   ```sh
   mkdir -p /var/tmp/kpg && chown postgres /var/tmp/kpg
   echo postgres > /var/tmp/kpg-pw && chown postgres /var/tmp/kpg-pw
   su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /var/tmp/kpg/data -A scram-sha-256 -U postgres --pwfile=/var/tmp/kpg-pw"
   su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/tmp/kpg/data -o '-p 5433 -k /var/tmp/kpg' -l /var/tmp/kpg/log start"
   export PGHOST=/var/tmp/kpg PGPORT=5433 PGUSER=postgres PGPASSWORD=postgres
   ```
   (`/tmp` may not be writable by the postgres user; `/var/tmp` is.) The cluster must ask every login for its
   password (scram, never `trust`): the sandbox, builder and reconciler refuse to start model-written code
   otherwise (R5-24). After a container restart: `rm -f /var/tmp/kpg/data/postmaster.pid` and start again.
   An OS user for model-written code: `useradd --system --no-create-home --shell /usr/sbin/nologin kkrun`,
   then `export KK_RUN_AS=kkrun`; the module tests run as root so they can start code as it.
2. Python deps: `python3 -m venv /var/tmp/kk-venv && /var/tmp/kk-venv/bin/pip install -r kernel/contract/requirements.txt -r kernel/providers/kernel-mcp/requirements.txt -r morphogen/modules/observer-otel/requirements.txt`, then `export KK_PYTHON=/var/tmp/kk-venv/bin/python` (a place the run user can read: not a private scratch directory).
   `sh kernel/contract/run.sh` → every provider passes every case for its slots.
3. `python3 scripts/check_boundary.py` → boundary ok.
4. Mutation check when you add or change a contract case: add a mutant to the provider's `tests/mutants.py` and run `$KK_PYTHON kernel/contract/mutants.py [provider]` (it breaks the check in a copy, `kernel/providers/_mutant`, runs the contract and deletes the copy): every mutant must fail.
5. Run the `invariant-reviewer` agent before committing.
6. CI (`.github/workflows/ci.yml`) runs steps 2 and 3 on every push.
