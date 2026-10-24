-- Module install: interview-encoder. Runs once as a superuser; applied by morphogen/modules/install.py.
-- Clearance comes from the default scope grants to kk_agent.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_interview_encoder') then
    create role kkm_interview_encoder nologin;
  end if;
end $$;
grant kk_agent to kkm_interview_encoder;
grant kkm_interview_encoder to kk_authenticator;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:interview-encoder', 'kkm_interview_encoder', 'software', 'Interview encoder')
on conflict (iri) do nothing;
reset role;
