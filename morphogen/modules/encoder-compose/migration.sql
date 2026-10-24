-- Module install: encoder-compose. Runs once as a superuser; applied by morphogen/modules/install.py.
-- Clearance comes from the default scope grants to kk_agent.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_encoder_compose') then
    create role kkm_encoder_compose nologin;
  end if;
end $$;
grant kk_agent to kkm_encoder_compose;
grant kkm_encoder_compose to kk_authenticator;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:encoder-compose', 'kkm_encoder_compose', 'software', 'Encoder: compose files')
on conflict (iri) do nothing;
reset role;
