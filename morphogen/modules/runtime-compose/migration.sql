-- Module install: runtime-compose. Runs once as a superuser; applied by morphogen/modules/install.py.
-- Clearance comes from the default scope grants to kk_agent. It reads plan steps and people's review decisions;
-- it never writes claims.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_runtime_compose') then
    create role kkm_runtime_compose nologin;
  end if;
end $$;
grant kk_agent to kkm_runtime_compose;
grant kkm_runtime_compose to kk_authenticator;
-- Its own login (R5-22): may switch only to kkm_runtime_compose; what the process holding the container socket gets.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_runtime_compose_login') then
    create role kkm_runtime_compose_login login noinherit;
  end if;
end $$;
grant kkm_runtime_compose to kkm_runtime_compose_login;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:runtime-compose', 'kkm_runtime_compose', 'software', 'Runtime: Docker Compose')
on conflict (iri) do nothing;
reset role;
