-- Module install: observer-otel. Runs once as a superuser; applied by morphogen/modules/install.py.
-- Clearance comes from the default scope grants to kk_agent.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_observer_otel') then
    create role kkm_observer_otel nologin;
  end if;
end $$;
grant kk_agent to kkm_observer_otel;
grant kkm_observer_otel to kk_authenticator;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:observer-otel', 'kkm_observer_otel', 'software', 'Observer: OpenTelemetry metrics')
on conflict (iri) do nothing;
reset role;
