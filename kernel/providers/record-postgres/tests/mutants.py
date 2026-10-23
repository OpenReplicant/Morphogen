"""Mutation check for the record-postgres provider: each mutant breaks one guarantee in a copy of the
provider (kernel/providers/_mutant) and the contract must fail on it. Exits non-zero if any mutant passes.
Usage: PGHOST=... PGUSER=<superuser> python3 kernel/providers/record-postgres/tests/mutants.py [name filter]
"""
import os, re, shutil, subprocess, sys
REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
SRC = f"{REPO}/kernel/providers/record-postgres"
MUT = f"{REPO}/kernel/providers/_mutant"
SQL = "schema/001_kernel.sql"
MUTANTS = [
  ("sequence instead of the locked feed head", [
    ("    update kernel.feed_head set seq = seq + 1 returning seq into v_seq;", "    v_seq := nextval('kernel.mut_seq');"),
    ("create table kernel.feed_head (", "create sequence kernel.mut_seq;\ncreate table kernel.feed_head (")]),
  ("no feed row", [("    insert into kernel.feed(seq, change_set, scope) values (v_seq, p_id, cs.target_scope);\n", "")]),
  ("feed without clearance", [("create policy read_by_scope on kernel.feed for select using (kernel.can_read(scope));",
                               "create policy read_by_scope on kernel.feed for select using (true);")]),
  ("as-of ignores claim record time", [("  where c.recorded_at <= known_at", "  where true")]),
  ("as-of takes the latest status", [("                   where s.claim_id = c.id and s.recorded_at <= known_at",
                                      "                   where s.claim_id = c.id")]),
  ("as-of takes the latest belief", [("           where b.claim_id = c.id and b.computed_at <= known_at",
                                      "           where b.claim_id = c.id")]),
  ("as-of ignores valid_to", [("    and (c.valid_to is null or c.valid_to > valid_at)\n", "")]),
  ("extension hook in the commit", [("\nreset role;\n", "\nreset role;\n"
     "create function public.mut_hook() returns trigger language plpgsql as $m$ begin return new; end $m$;\n"
     "create trigger mut_hook after insert on kernel.claim for each row execute function public.mut_hook();\n")]),
  ("agents may create in the kernel schema", [("grant usage on schema kernel to kk_agent;", "grant usage, create on schema kernel to kk_agent;")]),
  ("definer function without a search path", [("create function kernel.change_set_after_update() returns trigger\nlanguage plpgsql security definer set search_path = kernel, pg_catalog as $$",
                                               "create function kernel.change_set_after_update() returns trigger\nlanguage plpgsql security definer as $$")]),
]
survivors = []
for name, edits in [m for m in MUTANTS if len(sys.argv) < 2 or sys.argv[1] in m[0]]:
    if os.path.exists(MUT): shutil.rmtree(MUT)
    shutil.copytree(SRC, MUT)
    p = f"{MUT}/{SQL}"; s = open(p).read()
    for old, new in edits:
        assert s.count(old) == 1, (name, old); s = s.replace(old, new)
    open(p, "w").write(s)
    out = subprocess.run(["sh", f"{REPO}/kernel/contract/run.sh", "_mutant"], capture_output=True, text=True)
    lines = [l for l in (out.stdout + out.stderr).splitlines() if re.search(r"MISSING|CHECK FAILED|contract cases|ERROR", l)]
    print(("FAILS (good)" if out.returncode else "PASSES (bad)"), "-", name)
    for l in lines[:3]: print("    ", l[-150:])
    if not out.returncode: survivors.append(name)
shutil.rmtree(MUT)
sys.exit(1 if survivors else 0)
