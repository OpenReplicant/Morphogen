-- Provider install: encoder-sssom (R5-51). Runs once as a superuser; applied by kernel/providers/install.py.
-- Clearance comes from the default scope grants to kk_agent (kernel/providers/record-postgres/schema/002_bootstrap.sql).

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_encoder_sssom') then
    create role kkm_encoder_sssom nologin;
  end if;
end $$;
grant kk_agent to kkm_encoder_sssom;
grant kkm_encoder_sssom to kk_authenticator;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:encoder-sssom', 'kkm_encoder_sssom', 'software', 'SSSOM mapping set encoder')
on conflict (iri) do nothing;
reset role;
