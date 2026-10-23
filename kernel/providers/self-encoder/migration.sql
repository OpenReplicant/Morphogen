-- Provider install: self-encoder (T4). Runs once as a superuser; applied by kernel/providers/install.py.
-- Clearance comes from the default scope grants to kk_agent (kernel/providers/record-postgres/schema/002_bootstrap.sql).

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_self_encoder') then
    create role kkm_self_encoder nologin;
  end if;
end $$;
grant kk_agent to kkm_self_encoder;
grant kkm_self_encoder to kk_authenticator;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:self-encoder', 'kkm_self_encoder', 'software', 'Self-encoder: blueprint, providers, distribution')
on conflict (iri) do nothing;
reset role;
