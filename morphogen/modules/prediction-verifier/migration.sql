-- Module install: prediction-verifier. Runs once as a superuser; applied by morphogen/modules/install.py.
-- Clearance comes from the default scope grants to kk_agent. It writes verdicts only.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_prediction_verifier') then
    create role kkm_prediction_verifier nologin;
  end if;
end $$;
grant kk_agent to kkm_prediction_verifier;
grant kkm_prediction_verifier to kk_authenticator;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:prediction-verifier', 'kkm_prediction_verifier', 'software', 'Prediction verifier')
on conflict (iri) do nothing;

reset role;
