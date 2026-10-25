-- Module install: runtime-quadlet. Runs once as a superuser; applied by morphogen/modules/install.py.
-- Clearance comes from the default scope grants to kk_agent. It reads plan steps and people's review decisions;
-- it never writes claims.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_runtime_quadlet') then
    create role kkm_runtime_quadlet nologin;
  end if;
end $$;
grant kk_agent to kkm_runtime_quadlet;
grant kkm_runtime_quadlet to kk_authenticator;
-- Its own login (R5-22): may switch only to kkm_runtime_quadlet; what the process that starts the systemd units gets.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_runtime_quadlet_login') then
    create role kkm_runtime_quadlet_login login noinherit;
  end if;
end $$;
grant kkm_runtime_quadlet to kkm_runtime_quadlet_login;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:runtime-quadlet', 'kkm_runtime_quadlet', 'software', 'Runtime: Podman Quadlet')
on conflict (iri) do nothing;
reset role;
