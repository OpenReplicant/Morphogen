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

-- Who approved what (D-53, ported from rebuild 4 modules/actuator-compose): applied change sets that went
-- through the review lane, with the role that decided, for scopes the caller may read. Change sets stay
-- visible only to their submitter, validators and reviewers; an actuator needs to know that a person
-- approved a plan, and no more.
create or replace view api.review_decisions as
select c.id, c.target_scope, c.submitted_by, c.decided_by, c.decided_at
from kernel.change_set c
where c.lane = 'review' and c.status = 'applied' and c.decided_by is not null
  and kernel.can_read(c.target_scope);
grant select on api.review_decisions to kk_agent;
reset role;
