-- Module install: map-gaps. Runs once as a superuser; applied by morphogen/modules/install.py.
-- Clearance comes from the default scope grants to kk_agent.

do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_map_gaps') then
    create role kkm_map_gaps nologin;
  end if;
end $$;
grant kk_agent to kkm_map_gaps;
grant kkm_map_gaps to kk_authenticator;
-- Its own login (R5-22): may switch only to kkm_map_gaps; what the reconciler gives the gap finder's service.
do $$ begin
  if not exists (select 1 from pg_roles where rolname = 'kkm_map_gaps_login') then
    create role kkm_map_gaps_login login noinherit;
  end if;
end $$;
grant kkm_map_gaps to kkm_map_gaps_login;

set role kk_owner;
insert into kernel.agent(iri, db_role, kind, label)
values ('urn:kk:agent:map-gaps', 'kkm_map_gaps', 'software', 'Map gap finder')
on conflict (iri) do nothing;
reset role;
