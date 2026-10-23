---
name: dev
description: Set up the environment and run every check for this repo (Postgres for the contract suite, the boundary check). Use at the start of a session and before every commit.
---
# Environment and checks

0. Reference implementation (read-only, for porting): `git clone --depth 1 https://github.com/OpenReplicant/kernel ../kernel-reference`. Port from it; never push to it from this work.
1. Postgres 16+ superuser. If `/usr/lib/postgresql/16/bin` is missing: `apt-get install -y postgresql-16 postgresql-16-pgvector`. Then, in a cloud sandbox:
   ```sh
   mkdir -p /var/tmp/kpg && chown postgres /var/tmp/kpg
   su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /var/tmp/kpg/data -A trust"
   su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/tmp/kpg/data -o '-p 5433 -k /var/tmp/kpg' -l /var/tmp/kpg/log start"
   export PGHOST=/var/tmp/kpg PGPORT=5433 PGUSER=postgres
   ```
   (`/tmp` may not be writable by the postgres user; `/var/tmp` is.)
2. `sh kernel/contract/run.sh` → every case passes.
3. `python3 scripts/check_boundary.py` → boundary ok.
4. Mutation check when you add or change a contract case: add a mutant to `kernel/providers/record-postgres/tests/mutants.py` (it breaks the check in a copy, `kernel/providers/_mutant`, runs the contract and deletes the copy) and run it: every mutant must fail.
5. Run the `invariant-reviewer` agent before committing.
6. CI (`.github/workflows/ci.yml`) runs steps 2 and 3 on every push.
