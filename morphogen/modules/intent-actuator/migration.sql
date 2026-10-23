-- Module install: intent-actuator. Runs once as a superuser; applied by morphogen/modules/install.py.
-- Clearance comes from the default scope grants to kk_agent. It reads; it never writes claims.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_intent_actuator') then
    create role kkm_intent_actuator nologin;
  end if;
end $$;
grant kk_agent to kkm_intent_actuator;
grant kkm_intent_actuator to kk_authenticator;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:intent-actuator', 'kkm_intent_actuator', 'software', 'Actuator: commits to intent')
on conflict (iri) do nothing;

-- Who approved what: api.review_decisions, in the record store (record-postgres), which lists only
-- decisions made by a person.
reset role;
