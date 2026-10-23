#!/usr/bin/env sh
# Record-postgres provider suite, in a throwaway database (ported from rebuild 4).
# Usage: PGHOST=... PGUSER=<superuser> sh kernel/providers/record-postgres/tests/run.sh
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
db=${KK_TEST_DB:-kk_test}

dropdb --if-exists "$db"
for r in t_extractor t_verifier t_validator t_reviewer t_steward t_secret_readers t_bot_reviewer; do
  psql -d postgres -qc "drop role if exists $r" >/dev/null
done
createdb "$db"
# The feed test opens two more sessions from inside the server (dblink), so it needs a libpq
# connection string as the server sees it: the same host, port and credentials as this script.
conn="dbname=$db"
for kv in host:PGHOST port:PGPORT user:PGUSER password:PGPASSWORD; do
  eval "v=\${${kv#*:}:-}"
  [ -n "$v" ] && conn="$conn ${kv%%:*}=$v"
done
psql -d "$db" -v ON_ERROR_STOP=1 -v conn="$conn" -q \
  -f "$here/schema/001_kernel.sql" \
  -f "$here/schema/002_bootstrap.sql" \
  -f "$here/tests/test_kernel.sql"
