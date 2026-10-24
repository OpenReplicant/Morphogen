---
name: dev
description: Set up the environment and run every check for this repo (Postgres for the contract suite, the boundary check). Use at the start of a session and before every commit.
---
# Environment and checks

0. Reference implementation (read-only, for porting): `git clone --depth 1 https://github.com/OpenReplicant/kernel ../kernel-reference`. Port from it; never push to it from this work.
1. Postgres 16+ superuser. If `/usr/lib/postgresql/16/bin` is missing: `apt-get install -y postgresql-16 postgresql-16-pgvector`. Then, in a cloud sandbox:
   ```sh
   mkdir -p /var/tmp/kpg && chown postgres /var/tmp/kpg
   (umask 077; openssl rand -hex 24 > /root/.kk-pgpw)             # the superuser's password: random, root's alone
   install -o postgres -m 600 /root/.kk-pgpw /var/tmp/kpg-pw
   su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /var/tmp/kpg/data -A scram-sha-256 -U postgres --pwfile=/var/tmp/kpg-pw"
   rm /var/tmp/kpg-pw
   su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/tmp/kpg/data -o '-p 5433 -k /var/tmp/kpg' -l /var/tmp/kpg/log start"
   export PGHOST=/var/tmp/kpg PGPORT=5433 PGUSER=postgres PGPASSWORD=$(cat /root/.kk-pgpw)
   ```
   (`/tmp` may not be writable by the postgres user; `/var/tmp` is.) The cluster must ask every login for its
   password (scram, never `trust`): the sandbox, builder and reconciler refuse to start model-written code
   otherwise (R5-24). After a container restart: `rm -f /var/tmp/kpg/data/postmaster.pid` and start again.
   Never write a superuser's password in the repository or anywhere a run user can read: confined code reads
   the repository. OS users for model-written code, one per concurrent run:
   `for i in 1 2 3 4; do useradd --uid $((2900 + i)) --no-create-home --shell /usr/sbin/nologin kkrun$i; done`
   (uids nothing else runs as: `--system` can hand out 999, Postgres's uid in its container image),
   then `export KK_RUN_AS=kkrun1,kkrun2,kkrun3,kkrun4`; the module tests run as root so they can start code as them.
2. Python deps: `python3 -m venv /var/tmp/kk-venv && /var/tmp/kk-venv/bin/pip install -r kernel/contract/requirements.txt -r kernel/providers/kernel-mcp/requirements.txt -r morphogen/modules/observer-otel/requirements.txt`, then `export KK_PYTHON=/var/tmp/kk-venv/bin/python` (a place the run user can read: not a private scratch directory).
   `sh kernel/contract/run.sh` → every provider passes every case for its slots.
3. `python3 scripts/check_boundary.py` → boundary ok.
4. Mutation check when you add or change a contract case: add a mutant to the provider's `tests/mutants.py` and run `$KK_PYTHON kernel/contract/mutants.py [provider]` (it breaks the check in a copy, `kernel/providers/_mutant`, runs the contract and deletes the copy): every mutant must fail.
5. Run the `invariant-reviewer` agent before committing.
6. CI (`.github/workflows/ci.yml`) runs steps 2 and 3 on every push.
