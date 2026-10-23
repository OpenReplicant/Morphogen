-- Module install: planner. Runs once as a superuser; applied by morphogen/modules/install.py.
-- Clearance comes from the default scope grants to kk_agent.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_planner') then
    create role kkm_planner nologin;
  end if;
end $$;
grant kk_agent to kkm_planner;
grant kkm_planner to kk_authenticator;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:planner', 'kkm_planner', 'software', 'Planner: fixed actions with predictions')
on conflict (iri) do nothing;
reset role;
