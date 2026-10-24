-- Module install: design-blueprint. Runs once as a superuser; applied by morphogen/modules/install.py.
-- Clearance comes from the default scope grants to kk_agent.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_design_blueprint') then
    create role kkm_design_blueprint nologin;
  end if;
end $$;
grant kk_agent to kkm_design_blueprint;
grant kkm_design_blueprint to kk_authenticator;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:design-blueprint', 'kkm_design_blueprint', 'software', 'Design blueprint')
on conflict (iri) do nothing;
reset role;
