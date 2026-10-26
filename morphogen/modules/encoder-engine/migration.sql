-- Module install: encoder-engine. Runs once as a superuser; applied by morphogen/modules/install.py.
-- Clearance comes from the default scope grants to kk_agent.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_encoder_engine') then
    create role kkm_encoder_engine nologin;
  end if;
end $$;
grant kk_agent to kkm_encoder_engine;
grant kkm_encoder_engine to kk_authenticator;
-- Its own login (R5-22): may switch only to kkm_encoder_engine; what local.py gives the encoder's watch.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_encoder_engine_login') then
    create role kkm_encoder_engine_login login noinherit;
  end if;
end $$;
grant kkm_encoder_engine to kkm_encoder_engine_login;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:encoder-engine', 'kkm_encoder_engine', 'software', 'Encoder: what a container engine runs')
on conflict (iri) do nothing;
reset role;
