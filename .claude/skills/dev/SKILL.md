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
   then `for i in 1 2 3 4; do echo kkrun$i >> /etc/cron.deny; echo kkrun$i >> /etc/at.deny; done` (nothing a run
   leaves behind may run later) and `export KK_RUN_AS=kkrun1,kkrun2,kkrun3,kkrun4`; the module tests run as root so they can start code as them.
   Confined runs reach only the addresses their lease allows (R5-26): `nft` must be installed (`apt-get install -y nftables`).
   The intake filter needs gitleaks 8.30.1 on PATH (R5-29): download `gitleaks_8.30.1_linux_x64.tar.gz` from its GitHub release, check sha256 `551f6fc83ea457d62a0d98237cbad105af8d557003051f41f3e7ca7b3f2470eb`, put `gitleaks` in `/usr/local/bin`.
   The sandbox measures provider code on a cluster of its own (R5-26), made the same way on port 5434:
   ```sh
   mkdir -p /var/tmp/kpg-sbx && chown postgres /var/tmp/kpg-sbx
   (umask 077; openssl rand -hex 24 > /root/.kk-pgpw-sbx)
   install -o postgres -m 600 /root/.kk-pgpw-sbx /var/tmp/kpg-sbx-pw
   su postgres -c "/usr/lib/postgresql/16/bin/initdb -D /var/tmp/kpg-sbx/data -A scram-sha-256 -U postgres --pwfile=/var/tmp/kpg-sbx-pw"
   rm /var/tmp/kpg-sbx-pw
   su postgres -c "/usr/lib/postgresql/16/bin/pg_ctl -D /var/tmp/kpg-sbx/data -o '-p 5434 -k /var/tmp/kpg-sbx' -l /var/tmp/kpg-sbx/log start"
   export KK_SANDBOX_CLUSTER="host=/var/tmp/kpg-sbx port=5434 user=postgres password=$(cat /root/.kk-pgpw-sbx)"
   ```
2. Python deps: `python3 -m venv /var/tmp/kk-venv && /var/tmp/kk-venv/bin/pip install -r kernel/contract/requirements.txt -r kernel/providers/kernel-mcp/requirements.txt -r morphogen/modules/observer-otel/requirements.txt -r morphogen/modules/registry-lookup/requirements.txt`, then `export KK_PYTHON=/var/tmp/kk-venv/bin/python` (a place the run user can read: not a private scratch directory).
   `sh kernel/contract/run.sh` → every provider passes every case for its slots.
3. `python3 scripts/check_boundary.py` → boundary ok.
3a. Docker, for G3 (`morphogen/tests/test_g3.py`, `test_compose.py`; R5-25): if `docker info` fails, start the
   daemon with `nohup dockerd > /var/tmp/dockerd.log 2>&1 &` (after a container restart, remove
   `/var/run/docker/containerd/containerd.pid` first). The first run pulls podinfo and Redis; Docker Hub may
   answer 429: wait and retry. `KK_REQUIRE_DOCKER=1` makes `test_compose.py` fail instead of skip without it.
4. Mutation check when you add or change a contract case: add a mutant to the provider's `tests/mutants.py` and run `$KK_PYTHON kernel/contract/mutants.py [provider]` (it breaks the check in a copy, `kernel/providers/_mutant`, runs the contract and deletes the copy): every mutant must fail.
5. Run the `invariant-reviewer` agent before committing.
6. CI (`.github/workflows/ci.yml`) runs steps 2 and 3 on every push.
