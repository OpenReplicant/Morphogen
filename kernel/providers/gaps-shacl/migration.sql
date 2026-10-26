-- Module install: gaps-shacl. Runs once as a superuser; applied by kernel/providers/install.py.
-- Clearance comes from the default scope grants to kk_agent.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_gaps_shacl') then
    create role kkm_gaps_shacl nologin;
  end if;
end $$;
grant kk_agent to kkm_gaps_shacl;
grant kkm_gaps_shacl to kk_authenticator;
-- Its own login (R5-22): may switch only to kkm_gaps_shacl; what the reconciler gives the gap finder's service.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_gaps_shacl_login') then
    create role kkm_gaps_shacl_login login noinherit;
  end if;
end $$;
grant kkm_gaps_shacl to kkm_gaps_shacl_login;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:gaps-shacl', 'kkm_gaps_shacl', 'software', 'Shape-driven gap finder')
on conflict (iri) do nothing;
reset role;
