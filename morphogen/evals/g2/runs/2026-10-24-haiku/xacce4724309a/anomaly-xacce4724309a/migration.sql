-- Module install: anomaly. Runs once as a superuser; applied by morphogen/modules/install.py.
-- Clearance comes from the default scope grants to kk_agent.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_anomaly') then
    create role kkm_anomaly nologin;
  end if;
end $$;
grant kk_agent to kkm_anomaly;
grant kkm_anomaly to kk_authenticator;
-- Its own login (R5-22): may switch only to kkm_anomaly; what the reconciler and the sandbox give the
-- analyser's service, and a candidate for the analyser slot. Set its password at deploy time.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_anomaly_login') then
    create role kkm_anomaly_login login noinherit;
  end if;
end $$;
grant kkm_anomaly to kkm_anomaly_login;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:anomaly', 'kkm_anomaly', 'software', 'Anomaly processor')
on conflict (iri) do nothing;
reset role;
