-- Module install: observer-prometheus. Runs once as a superuser; applied by morphogen/modules/install.py.
-- Clearance comes from the default scope grants to kk_agent.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_observer_prometheus') then
    create role kkm_observer_prometheus nologin;
  end if;
end $$;
grant kk_agent to kkm_observer_prometheus;
grant kkm_observer_prometheus to kk_authenticator;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:observer-prometheus', 'kkm_observer_prometheus', 'software', 'Observer: Prometheus metrics endpoints')
on conflict (iri) do nothing;
reset role;
