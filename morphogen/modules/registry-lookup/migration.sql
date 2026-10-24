-- Module install: registry-lookup. Runs once as a superuser; applied by morphogen/modules/install.py.
-- Clearance comes from the default scope grants to kk_agent.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_registry_lookup') then
    create role kkm_registry_lookup nologin;
  end if;
end $$;
grant kk_agent to kkm_registry_lookup;
grant kkm_registry_lookup to kk_authenticator;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:registry-lookup', 'kkm_registry_lookup', 'software', 'Catalog lookup')
on conflict (iri) do nothing;
reset role;
