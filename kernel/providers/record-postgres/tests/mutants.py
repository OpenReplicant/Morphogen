"""Mutants for the record-postgres provider (run by kernel/contract/mutants.py)."""

SQL = "schema/001_kernel.sql"

MUTANTS = [
  ("sequence instead of the locked feed head", SQL, [
    ("until commit.\n    update kernel.feed_head set seq = seq + 1 returning seq into v_seq;",
     "until commit.\n    v_seq := nextval('kernel.mut_seq');"),
    ("create table kernel.feed_head (", "create sequence kernel.mut_seq;\ncreate table kernel.feed_head (")]),
  ("no feed row", SQL, [("    insert into kernel.feed(seq, change_set, scope) values (v_seq, p_id, cs.target_scope);\n", "")]),
  ("feed without clearance", SQL, [("create policy read_by_scope on kernel.feed for select using (kernel.can_read(scope));",
                               "create policy read_by_scope on kernel.feed for select using (true);")]),
  ("as-of ignores claim record time", SQL, [("  where c.recorded_at <= known_at", "  where true")]),
  ("as-of takes the latest status", SQL, [("                   where s.claim_id = c.id and s.recorded_at <= known_at",
                                      "                   where s.claim_id = c.id")]),
  ("as-of takes the latest belief", SQL, [("           where b.claim_id = c.id and b.computed_at <= known_at",
                                      "           where b.claim_id = c.id")]),
  ("as-of ignores valid_to", SQL, [("    and (c.valid_to is null or c.valid_to > valid_at)\n", "")]),
  ("extension hook in the commit", SQL, [("\nreset role;\n", "\nreset role;\n"
     "create function public.mut_hook() returns trigger language plpgsql as $m$ begin return new; end $m$;\n"
     "create trigger mut_hook after insert on kernel.claim for each row execute function public.mut_hook();\n")]),
  ("agents may create in the kernel schema", SQL, [("grant usage on schema kernel to kk_agent;", "grant usage, create on schema kernel to kk_agent;")]),
  ("definer function without a search path", SQL, [("create function kernel.change_set_after_update() returns trigger\nlanguage plpgsql security definer set search_path = kernel, pg_catalog as $$",
                                               "create function kernel.change_set_after_update() returns trigger\nlanguage plpgsql security definer as $$")]),
  ("concurrency failure marks the change set invalid", SQL, [("    if sqlstate in ('40001', '40P01', '55P03') then\n      raise;\n    end if;\n", "")]),
  ("non-kernel function in a column default", SQL, [("\nreset role;\n", "\nreset role;\n" "create function public.mut_fn() returns text language sql as $m$ select 'x' $m$;\n"
     "alter table kernel.claim add column mut text default public.mut_fn();\n")]),
  ("non-kernel function in a policy", SQL, [("\nreset role;\n", "\nreset role;\n" "create function public.mut_fn() returns boolean language sql as $m$ select true $m$;\n"
     "create policy mut on kernel.change_set for update using (public.mut_fn());\n")]),
  ("apply calls a non-kernel function", SQL, [("    v_state := 'applied';\n  exception", "    perform public.mut_fn();\n    v_state := 'applied';\n  exception"),
     ("\nreset role;\n", "\nreset role;\n" "create function public.mut_fn() returns text language sql as $m$ select 'x' $m$;\n")]),
  ("redaction not in the feed", SQL, [("    insert into kernel.feed(seq, redaction, target_kind, target_id, scope)\n"
                                    "    values (v_seq, new.id, new.target_kind, new.target_id, v_scope);\n", "")]),
  ("redaction in the feed under the default scope", SQL, [("    values (v_seq, new.id, new.target_kind, new.target_id, v_scope);",
                                                        "    values (v_seq, new.id, new.target_kind, new.target_id, 'urn:kk:scope:default');")]),
  ("redaction feed entry names no claims", SQL, [("              where f.target_kind = 'claim' and c.id = f.target_id::uuid", "              where false")]),
  ("artifact redaction names no claims", SQL, [("              where f.target_kind = 'artifact' and r.artifact = f.target_id) x",
                                             "              where false) x")]),
  ("redaction of a missing target takes a number", SQL, [("  if v_scope is not null then\n    update kernel.feed_head",
                                                       "  v_scope := coalesce(v_scope, 'urn:kk:scope:default');\n  if true then\n    update kernel.feed_head")]),
  ("a redacted artifact may be quoted again", SQL, [("            if v_art.redacted_at is not null then", "            if false then")]),
  ("rows about a claim visible without it", SQL, [("  select exists (select 1 from kernel.claim c where c.id = p_claim)\n$$;", "  select true\n$$;")]),
  ("review decisions without a person", SQL, [("join kernel.agent a on a.db_role = c.decided_by and a.kind = 'person'\n", "")]),
  ("a claim id in another spelling escapes review", SQL, [("           and pg_input_is_valid(op->>'claim', 'uuid')",
                                                            "           and op->>'claim' ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'")]),
  ("a mapping's status changed without review", SQL, [("       or (op->>'op' = 'set_status'\n", "       or (false and op->>'op' = 'set_status'\n")]),
]
