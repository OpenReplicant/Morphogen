-- Kernel v0 invariant tests. Run against a fresh database after 001 and 002:
--   psql -v ON_ERROR_STOP=1 -f 001_kernel.sql -f 002_bootstrap.sql -f tests/test_kernel.sql
-- Must be run by a superuser (it creates test roles and switches between them).
-- Any failed expectation raises and stops the script; the last line prints ALL KERNEL TESTS PASSED.

\set QUIET on
\set ON_ERROR_STOP on
\o /dev/null

-- ---------------------------------------------------------------- helpers
create function public.expect_error(p_sql text, p_code text) returns void
language plpgsql as $$
declare v_ok boolean := false;
begin
  begin
    execute p_sql;
  exception when others then
    if sqlstate = p_code then v_ok := true;
    else raise exception 'expected % but got %: %', p_code, sqlstate, sqlerrm;
    end if;
  end;
  if not v_ok then raise exception 'expected error % but it succeeded: %', p_code, p_sql; end if;
end $$;

create function public.check(p_cond boolean, p_msg text) returns void
language plpgsql as $$
begin
  if p_cond is not true then raise exception 'CHECK FAILED: %', p_msg; end if;
  raise notice 'ok: %', p_msg;
end $$;

-- Waits until a dblink session's query has finished or is waiting on a lock (at most 10 s), so a
-- concurrency test never depends on how long a sleep takes on a given machine.
create function public.wait_blocked_or_done(p_conn text, p_pid int) returns text
language plpgsql as $$
begin
  for i in 1..200 loop
    if dblink_is_busy(p_conn) = 0 then return 'done'; end if;
    if exists (select 1 from pg_stat_activity where pid = p_pid and wait_event_type = 'Lock') then
      return 'blocked';
    end if;
    perform pg_sleep(0.05);
  end loop;
  raise exception 'session % neither finished nor waited on a lock', p_conn;
end $$;

-- ---------------------------------------------------------------- fixtures
create role t_extractor nologin;  grant kk_agent to t_extractor;
create role t_verifier nologin;   grant kk_agent to t_verifier;
create role t_validator nologin;  grant kk_validator to t_validator;
create role t_reviewer nologin;   grant kk_reviewer to t_reviewer;
create role t_steward nologin;    grant kk_steward to t_steward;
create role t_secret_readers nologin; grant t_secret_readers to t_extractor;

insert into kernel.prefix values ('ex', 'http://example.org/');
insert into kernel.agent(iri, db_role, kind, label) values
  ('urn:kk:agent:extractor', 't_extractor', 'software', 'Test extractor'),
  ('urn:kk:agent:verifier',  't_verifier',  'software', 'Test verifier'),
  ('urn:kk:agent:validator', 't_validator', 'software', 'Test validator'),
  ('urn:kk:agent:reviewer',  't_reviewer',  'person',   'Test reviewer'),
  ('urn:kk:agent:steward',   't_steward',   'person',   'Test steward');
insert into kernel.scope values ('urn:kk:scope:secret', 'Secret test scope');
insert into kernel.scope_grant values ('urn:kk:scope:secret', 't_secret_readers', true, true);
grant t_secret_readers to t_validator;   -- validators must be cleared for the scopes they validate

-- ---------------------------------------------------------------- 1. a normal extracted claim
set role t_extractor;
select api.start_run('ex:module/extractor') as run1 \gset
select set_config('t.run1', :'run1', false);

select api.submit_change_set(jsonb_build_object(
  'idempotency_key', 'test:cs1',
  'attributed_to', 'urn:kk:agent:extractor',
  'generated_by', current_setting('t.run1'),
  'target_scope', 'urn:kk:scope:default',
  'ops', jsonb_build_array(jsonb_build_object(
     'op', 'add_claim', 'ref', 'c1',
     'subject', 'ex:service/billing', 'predicate', 'rdfs:label',
     'object', jsonb_build_object('value', jsonb_build_object('@value', 'Billing service')),
     'evidence_type', 'extracted',
     'references', jsonb_build_array(jsonb_build_object(
        'source_uri', 'https://example.org/README.md', 'quote', 'The Billing service handles invoices')))))
)->>'id' as cs1 \gset
select set_config('t.cs1', :'cs1', false);

select public.check((select status from api.change_sets where id = current_setting('t.cs1')::uuid) = 'submitted',
                    'change set starts as submitted');
select public.expect_error($$select api.record_validation(current_setting('t.cs1')::uuid, true)$$, '42501');
select public.expect_error($$update kernel.claim set qualifiers = '{}'$$, '42501');
select public.check(
  (api.submit_change_set(jsonb_build_object('idempotency_key','test:cs1','attributed_to','urn:kk:agent:extractor',
     'generated_by', current_setting('t.run1'),'target_scope','urn:kk:scope:default',
     'ops', '[{"op":"add_entity","iri":"ex:x"}]'::jsonb))->>'id') = current_setting('t.cs1'),
  'resubmitting the same idempotency key returns the same change set');

-- attribution cannot be spoofed
select public.expect_error($$select api.submit_change_set(jsonb_build_object(
  'idempotency_key','test:spoof','attributed_to','urn:kk:agent:verifier',
  'generated_by', current_setting('t.run1'),'target_scope','urn:kk:scope:default',
  'ops','[{"op":"add_entity","iri":"ex:y"}]'::jsonb))$$, 'KK010');
reset role;

-- validation by the submitter is refused; by a validator it applies
set role t_validator;
select public.check(api.record_validation(current_setting('t.cs1')::uuid, true, '{"shapes":"ok"}') = 'applied',
                    'validated auto-lane change set is applied');
reset role;
-- record time r0: claim1 known, no belief, no newer label (used by section 10)
select pg_sleep(0.01);
select set_config('t.r0', clock_timestamp()::text, false);
select pg_sleep(0.01);

set role t_extractor;
select id as claim1 from api.claims where change_set = current_setting('t.cs1')::uuid \gset
select set_config('t.claim1', :'claim1', false);
select public.check((select count(*) from kernel.claim_reference where claim_id = current_setting('t.claim1')::uuid) = 1,
                    'claim keeps its reference and quote');
select public.check((select attributed_to from api.claims where id = current_setting('t.claim1')::uuid) = 'urn:kk:agent:extractor',
                    'claim is attributed to the submitting agent');
reset role;

-- ---------------------------------------------------------------- 2. invariant 1 violations become invalid
set role t_extractor;
select api.submit_change_set(jsonb_build_object(
  'idempotency_key','test:noquote','attributed_to','urn:kk:agent:extractor',
  'generated_by', current_setting('t.run1'),'target_scope','urn:kk:scope:default',
  'ops', jsonb_build_array(jsonb_build_object('op','add_claim','subject','ex:a','predicate','rdfs:label',
     'object', jsonb_build_object('value', jsonb_build_object('@value','A')),
     'evidence_type','extracted','references', jsonb_build_array(jsonb_build_object('source_uri','https://example.org/a'))))))->>'id' as cs_noquote \gset
select api.submit_change_set(jsonb_build_object(
  'idempotency_key','test:unapproved','attributed_to','urn:kk:agent:extractor',
  'generated_by', current_setting('t.run1'),'target_scope','urn:kk:scope:default',
  'ops', jsonb_build_array(jsonb_build_object('op','add_claim','subject','ex:a','predicate','ex:madeUpProperty',
     'object', jsonb_build_object('entity','ex:b'),
     'evidence_type','deterministic','references', jsonb_build_array(jsonb_build_object('source_uri','https://example.org/a'))))))->>'id' as cs_unapproved \gset
reset role;
set role t_validator;
select public.check(api.record_validation(:'cs_noquote'::uuid, true) = 'invalid', 'extracted claim without a quote is rejected');
select public.check((select validation_report->>'sqlstate' from api.change_sets where id = :'cs_noquote'::uuid) = 'KK033', 'reason recorded: missing quote');
select public.check(api.record_validation(:'cs_unapproved'::uuid, true) = 'invalid', 'claim with an unapproved predicate is rejected');
reset role;

-- ---------------------------------------------------------------- 3. vocabulary changes take the review lane
set role t_extractor;
select api.submit_change_set(jsonb_build_object(
  'idempotency_key','test:newprop','attributed_to','urn:kk:agent:extractor',
  'generated_by', current_setting('t.run1'),'target_scope','urn:kk:scope:vocab','lane','auto',
  'ops', jsonb_build_array(jsonb_build_object('op','add_claim','subject','ex:dependsOn','predicate','rdf:type',
     'object', jsonb_build_object('entity','owl:ObjectProperty'),
     'evidence_type','testimony','references', jsonb_build_array(jsonb_build_object('source_uri','https://example.org/proposal'))))))
  as newprop \gset
select public.check((:'newprop'::jsonb)->>'lane' = 'review', 'typing a new property is forced into the review lane');
select set_config('t.cs_newprop', (:'newprop'::jsonb)->>'id', false);
reset role;
set role t_validator;
select public.check(api.record_validation(current_setting('t.cs_newprop')::uuid, true) = 'awaiting_review', 'valid review-lane change set waits for a reviewer');
reset role;
set role t_extractor;
select public.expect_error($$select api.review(current_setting('t.cs_newprop')::uuid, true)$$, '42501');
reset role;
set role t_reviewer;
select public.check(api.review(current_setting('t.cs_newprop')::uuid, true, 'looks right') = 'applied', 'reviewer approval applies it');
reset role;
select public.check(kernel.is_approved_property('http://example.org/dependsOn'), 'the new property is now approved');

-- ---------------------------------------------------------------- 4. scopes, clearance and derived claims
set role t_extractor;
select api.submit_change_set(jsonb_build_object(
  'idempotency_key','test:secret','attributed_to','urn:kk:agent:extractor',
  'generated_by', current_setting('t.run1'),'target_scope','urn:kk:scope:secret',
  'ops', jsonb_build_array(jsonb_build_object('op','add_claim','ref','s1','subject','ex:service/billing','predicate','ex:dependsOn',
     'object', jsonb_build_object('entity','ex:service/ledger'),
     'evidence_type','deterministic','references', jsonb_build_array(jsonb_build_object('source_uri','https://example.org/private.yaml'))))))->>'id' as cs_secret \gset
reset role;
set role t_validator;
select public.check(api.record_validation(:'cs_secret'::uuid, true) = 'applied', 'secret-scope claim applied');
reset role;
set role t_reviewer;
select public.check((select count(*) from api.change_sets where target_scope = 'urn:kk:scope:secret') = 0,
                    'a reviewer without clearance cannot see secret change sets');
reset role;

set role t_extractor;
select public.check((select count(*) from api.claims where scope = 'urn:kk:scope:secret') = 1, 'cleared agent sees the secret claim');
select id as secret_claim from api.claims where scope = 'urn:kk:scope:secret' \gset
select set_config('t.secret_claim', :'secret_claim', false);
-- derive a public claim from a secret one: must be refused (invariant 3)
select api.submit_change_set(jsonb_build_object(
  'idempotency_key','test:leak','attributed_to','urn:kk:agent:extractor',
  'generated_by', current_setting('t.run1'),'target_scope','urn:kk:scope:default',
  'ops', jsonb_build_array(jsonb_build_object('op','add_claim','subject','ex:service/billing','predicate','rdfs:comment',
     'object', jsonb_build_object('value', jsonb_build_object('@value','depends on the ledger')),
     'evidence_type','inferred','derived_from', jsonb_build_array(current_setting('t.secret_claim'))))))->>'id' as cs_leak \gset
reset role;
set role t_verifier;
select public.check((select count(*) from api.claims where scope = 'urn:kk:scope:secret') = 0, 'uncleared agent cannot see the secret claim');
select public.check((select count(*) from kernel.claim_reference r join kernel.claim c on c.id = r.claim_id where c.scope = 'urn:kk:scope:secret') = 0,
                    'uncleared agent cannot see its references either');
select public.expect_error($$select api.submit_change_set(jsonb_build_object(
  'idempotency_key','test:nowrite','attributed_to','urn:kk:agent:verifier',
  'generated_by', (select api.start_run('ex:module/verifier'))::text,'target_scope','urn:kk:scope:secret',
  'ops','[{"op":"add_entity","iri":"ex:z"}]'::jsonb))$$, 'KK012');
reset role;
set role t_validator;
select public.check(api.record_validation(:'cs_leak'::uuid, true) = 'invalid', 'deriving into a less restrictive scope is rejected');
select public.check((select validation_report->>'sqlstate' from api.change_sets where id = :'cs_leak'::uuid) = 'KK037', 'reason recorded: scope leak');
reset role;

-- ---------------------------------------------------------------- 5. no method verifies its own output
set role t_extractor;
select api.submit_change_set(jsonb_build_object(
  'idempotency_key','test:selfverify','attributed_to','urn:kk:agent:extractor',
  'generated_by', current_setting('t.run1'),'target_scope','urn:kk:scope:default',
  'ops', jsonb_build_array(jsonb_build_object('op','add_verification','claim', current_setting('t.claim1'),
     'verdict','supported','method','ex:module/extractor'))))->>'id' as cs_self \gset
reset role;
set role t_verifier;
select api.start_run('ex:module/verifier') as run2 \gset
select api.submit_change_set(jsonb_build_object(
  'idempotency_key','test:verify','attributed_to','urn:kk:agent:verifier',
  'generated_by', :'run2','target_scope','urn:kk:scope:default',
  'ops', jsonb_build_array(
     jsonb_build_object('op','add_verification','claim', current_setting('t.claim1'),
                        'verdict','supported','method','ex:module/verifier'),
     jsonb_build_object('op','add_belief','claim', current_setting('t.claim1'),
                        'model','urn:kk:module:belief-corroboration-v0','value',0.75,
                        'explanation', jsonb_build_object('independent_sources',1)))))->>'id' as cs_verify \gset
reset role;
set role t_validator;
select public.check(api.record_validation(:'cs_self'::uuid, true) = 'invalid', 'self-verification is rejected');
select public.check(api.record_validation(:'cs_verify'::uuid, true) = 'applied', 'independent verification and belief are applied');
reset role;
set role t_extractor;
select public.check((select belief from api.claims where id = current_setting('t.claim1')::uuid) = 0.75, 'api.claims shows the active model''s belief');
reset role;

-- ---------------------------------------------------------------- 6. optimistic concurrency and supersession
-- record time r1: claim1 has its belief and is not yet superseded (used by section 10)
select pg_sleep(0.01);
select set_config('t.r1', clock_timestamp()::text, false);
select pg_sleep(0.01);
set role t_extractor;
select api.submit_change_set(jsonb_build_object(
  'idempotency_key','test:stale','attributed_to','urn:kk:agent:extractor',
  'generated_by', current_setting('t.run1'),'target_scope','urn:kk:scope:default',
  'ops', jsonb_build_array(jsonb_build_object('op','set_status','claim', current_setting('t.claim1'),
     'status','deprecated','reason','superseded','expect_status','preferred'))))->>'id' as cs_stale \gset
select api.submit_change_set(jsonb_build_object(
  'idempotency_key','test:supersede','attributed_to','urn:kk:agent:extractor',
  'generated_by', current_setting('t.run1'),'target_scope','urn:kk:scope:default',
  'ops', jsonb_build_array(
    jsonb_build_object('op','add_claim','ref','new','subject','ex:service/billing','predicate','rdfs:label',
       'object', jsonb_build_object('value', jsonb_build_object('@value','Billing API')),
       'evidence_type','extracted','references', jsonb_build_array(jsonb_build_object(
          'source_uri','https://example.org/README.md','quote','The Billing API handles invoices'))),
    jsonb_build_object('op','set_status','claim', current_setting('t.claim1'),
       'status','deprecated','reason','superseded','replaced_by','new','expect_status','normal'))))->>'id' as cs_supersede \gset
reset role;
set role t_validator;
select public.check(api.record_validation(:'cs_stale'::uuid, true) = 'conflict', 'stale expect_status is a conflict, not an overwrite');
select public.check(api.record_validation(:'cs_supersede'::uuid, true) = 'applied', 'supersession applied');
reset role;
set role t_extractor;
select public.check((select status from api.claims where id = current_setting('t.claim1')::uuid) = 'deprecated', 'old claim deprecated, not deleted');
select public.check((select (api.explain(current_setting('t.claim1')::uuid)->'status'->0->>'replaced_by') is not null), 'explain shows what replaced it');
reset role;

-- ---------------------------------------------------------------- 7. immutability and redaction
select public.expect_error($$delete from kernel.claim$$, 'KK001');
select public.expect_error($$update kernel.claim set qualifiers = '{"x":1}'$$, 'KK001');

set role t_extractor;
select public.expect_error($$select api.redact('claim', current_setting('t.claim1'), 'test', current_setting('t.run1')::uuid)$$, '42501');
reset role;
set role t_steward;
select api.start_run(null) as run3 \gset
select api.redact('claim', current_setting('t.claim1'), 'erasure request #1', :'run3'::uuid);
reset role;
set role t_extractor;
select public.check((select object_value is null and redacted_at is not null from api.claims where id = current_setting('t.claim1')::uuid),
                    'redaction removes the value but keeps the claim');
select public.check((select quote is null from kernel.claim_reference where claim_id = current_setting('t.claim1')::uuid),
                    'redaction removes the quote');
select public.check((select statement_key is not null and attributed_to is not null from api.claims where id = current_setting('t.claim1')::uuid),
                    'lineage and attribution survive redaction');
reset role;

-- ---------------------------------------------------------------- 8. runs
set role t_verifier;
select public.expect_error($$select api.finish_run(current_setting('t.run1')::uuid, 'succeeded')$$, 'KK003');
reset role;
set role t_extractor;
select api.finish_run(current_setting('t.run1')::uuid, 'succeeded', '{"tokens": 1200}');
select public.check((select status = 'succeeded' and ended_at is not null from kernel.run where id = current_setting('t.run1')::uuid), 'agent finishes its own run with cost');
reset role;

-- ---------------------------------------------------------------- 9. change feed (D-86)
select public.check(
  (select count(*) from kernel.change_set where status = 'applied') = (select count(*) from kernel.feed)
  and not exists (select 1 from kernel.feed f join kernel.change_set c on c.id = f.change_set where c.status <> 'applied'),
  'every applied change set has one feed number');
select public.check(
  (select min(seq) = 1 and max(seq) = count(*) from kernel.feed),
  'feed numbers are consecutive');
select public.check(
  not exists (select 1 from kernel.feed where change_set in (:'cs_noquote'::uuid, :'cs_leak'::uuid, :'cs_stale'::uuid)),
  'a failed apply takes no feed number');

set role t_extractor;
select id as claim_new from api.claims where change_set = :'cs_supersede'::uuid \gset
select public.check(
  (select claim_ids @> array[current_setting('t.claim1')::uuid, :'claim_new'::uuid]
          and predicates = array[kernel.expand('rdfs:label')]
     from api.feed(0, 100000) where change_set_id = :'cs_supersede'::uuid)
  and (select claim_ids = array[current_setting('t.claim1')::uuid]
         from api.feed(0, 100000) where change_set_id = :'cs_verify'::uuid),
  'the feed lists the claims a change set added or recorded on');
select public.check(
  (select array_agg(seq order by seq) = array_agg(seq) from api.feed(2, 3))
  and (select min(seq) = 3 from api.feed(2, 3)) and (select count(*) = 3 from api.feed(2, 3)),
  'the feed returns what comes after the cursor, in order');
select public.check(exists (select 1 from api.feed(0, 100000) where scope = 'urn:kk:scope:secret'),
                    'cleared agent sees secret change sets in the feed');
reset role;
set role t_verifier;
select public.check(not exists (select 1 from api.feed(0, 100000) where scope = 'urn:kk:scope:secret'),
                    'uncleared agent does not see secret change sets in the feed');
reset role;

-- Two applies at once. A applies first but commits last; a reader takes its cursor while A is open.
-- After both commit, reading after that cursor must return both (no commit is skipped).
set role t_extractor;
select api.submit_change_set(jsonb_build_object('idempotency_key','test:feed-a','attributed_to','urn:kk:agent:extractor',
  'generated_by', current_setting('t.run1'),'target_scope','urn:kk:scope:default',
  'ops','[{"op":"add_entity","iri":"ex:feed/a"}]'::jsonb))->>'id' as cs_fa \gset
select api.submit_change_set(jsonb_build_object('idempotency_key','test:feed-b','attributed_to','urn:kk:agent:extractor',
  'generated_by', current_setting('t.run1'),'target_scope','urn:kk:scope:default',
  'ops','[{"op":"add_entity","iri":"ex:feed/b"}]'::jsonb))->>'id' as cs_fb \gset
reset role;
create extension if not exists dblink schema public;   -- test harness only; the kernel uses no extensions
select dblink_connect('a', :'conn');
select dblink_connect('b', :'conn');
select dblink_exec('a', 'begin');
select dblink_exec('a', 'set role t_validator');
select dblink_exec('b', 'set role t_validator');
select pid as pid_b from dblink('b', 'select pg_backend_pid()') as t(pid int) \gset
select * from dblink('a', format('select api.record_validation(%L::uuid, true)', :'cs_fa')) as t(state text);
select dblink_send_query('b', format('select api.record_validation(%L::uuid, true)', :'cs_fb'));
select public.wait_blocked_or_done('b', :pid_b);
set role t_extractor;
select coalesce(max(seq), 0) as feed_cursor from api.feed(0, 100000) \gset
reset role;
select dblink_exec('a', 'commit');
select * from dblink_get_result('b') as t(state text);
select * from dblink_get_result('b') as t(state text);
set role t_extractor;
select public.check(
  (select count(*) from api.feed(:'feed_cursor'::bigint, 100000) where change_set_id in (:'cs_fa'::uuid, :'cs_fb'::uuid)) = 2,
  'a cursor skips no change set that commits concurrently');
reset role;

-- The same race under repeatable read: B cannot take the next number once A commits. That is a
-- retry for the caller, never a verdict on the change set.
set role t_extractor;
select api.submit_change_set(jsonb_build_object('idempotency_key','test:feed-c','attributed_to','urn:kk:agent:extractor',
  'generated_by', current_setting('t.run1'),'target_scope','urn:kk:scope:default',
  'ops','[{"op":"add_entity","iri":"ex:feed/c"}]'::jsonb))->>'id' as cs_fc \gset
select api.submit_change_set(jsonb_build_object('idempotency_key','test:feed-d','attributed_to','urn:kk:agent:extractor',
  'generated_by', current_setting('t.run1'),'target_scope','urn:kk:scope:default',
  'ops','[{"op":"add_entity","iri":"ex:feed/d"}]'::jsonb))->>'id' as cs_fd \gset
reset role;
select dblink_exec('a', 'begin');
select * from dblink('a', format('select api.record_validation(%L::uuid, true)', :'cs_fc')) as t(state text);
select dblink_exec('b', 'begin isolation level repeatable read');
select dblink_send_query('b', format('select api.record_validation(%L::uuid, true)', :'cs_fd'));
select public.wait_blocked_or_done('b', :pid_b);
select dblink_exec('a', 'commit');
select count(*) as rr_rows from dblink_get_result('b', false) as t(state text) \gset
select dblink_error_message('b') as rr_error \gset
select count(*) from dblink_get_result('b', false) as t(state text);
select dblink_exec('b', 'rollback');
select public.check(
  (select status from kernel.change_set where id = :'cs_fd'::uuid) = 'submitted'
  and :rr_rows = 0 and :'rr_error' like '%serialize%',
  'a concurrent apply that cannot serialize is retried, not marked invalid');
select * from dblink('b', format('select api.record_validation(%L::uuid, true)', :'cs_fd')) as t(state text);
select public.check((select status from kernel.change_set where id = :'cs_fd'::uuid) = 'applied',
                    'the retried apply succeeds');
select dblink_disconnect('a');
select dblink_disconnect('b');

-- ---------------------------------------------------------------- 10. bitemporal as-of (D-09)
set role t_extractor;
select api.submit_change_set(jsonb_build_object('idempotency_key','test:validtime','attributed_to','urn:kk:agent:extractor',
  'generated_by', current_setting('t.run1'),'target_scope','urn:kk:scope:default',
  'ops', jsonb_build_array(jsonb_build_object('op','add_claim','subject','ex:service/billing','predicate','rdfs:comment',
     'object', jsonb_build_object('value', jsonb_build_object('@value','ran on the old cluster')),
     'valid_from','2020-01-01T00:00:00Z','valid_to','2021-01-01T00:00:00Z',
     'evidence_type','deterministic','references', jsonb_build_array(jsonb_build_object('source_uri','https://example.org/history'))))))->>'id' as cs_vt \gset
reset role;
set role t_validator;
select api.record_validation(:'cs_vt'::uuid, true);
reset role;

set role t_extractor;
select public.check(
  exists (select 1 from api.claims_as_of(now(), current_setting('t.r0')::timestamptz) where id = current_setting('t.claim1')::uuid)
  and not exists (select 1 from api.claims_as_of(now(), current_setting('t.r0')::timestamptz) where id = :'claim_new'::uuid),
  'as of an earlier record time, later claims are not yet known');
select public.check(
  (select status = 'normal' and belief is null from api.claims_as_of(now(), current_setting('t.r0')::timestamptz)
    where id = current_setting('t.claim1')::uuid)
  and (select status = 'normal' and belief = 0.75 from api.claims_as_of(now(), current_setting('t.r1')::timestamptz)
    where id = current_setting('t.claim1')::uuid)
  and (select status = 'deprecated' from api.claims_as_of() where id = current_setting('t.claim1')::uuid),
  'as of an earlier record time, status and belief are what was recorded then');
select public.check(
  exists (select 1 from api.claims_as_of('2020-06-01', now()) where change_set = :'cs_vt'::uuid)
  and not exists (select 1 from api.claims_as_of('2022-06-01', now()) where change_set = :'cs_vt'::uuid)
  and not exists (select 1 from api.claims_as_of('2019-06-01', now()) where change_set = :'cs_vt'::uuid),
  'a claim is returned only at valid times inside its interval');
select public.check(
  (select object_value is null from api.claims_as_of(now(), current_setting('t.r0')::timestamptz)
    where id = current_setting('t.claim1')::uuid),
  'redacted content stays removed at earlier record times');
select public.check(exists (select 1 from api.claims_as_of() where scope = 'urn:kk:scope:secret'),
                    'cleared agent sees the secret claim as of now');
reset role;
set role t_verifier;
select public.check(not exists (select 1 from api.claims_as_of() where scope = 'urn:kk:scope:secret')
                    and not exists (select 1 from api.claims_as_of(now() - interval '1 day', current_setting('t.r1')::timestamptz)
                                    where scope = 'urn:kk:scope:secret')
                    and not exists (select 1 from api.claims_as_of(current_setting('t.r1')::timestamptz, now())
                                    where scope = 'urn:kk:scope:secret'),
                    'uncleared agent cannot see the secret claim as of any time');
reset role;

-- ---------------------------------------------------------------- 11. no extension code in the commit
-- Applying runs only what the triggers on kernel tables call. Those must be the kernel's own
-- functions, in trusted languages, with pinned search paths, in a schema nobody else can write.
select public.check(not exists (
  select 1 from pg_trigger t
    join pg_class c on c.oid = t.tgrelid
    join pg_proc p on p.oid = t.tgfoid
   where c.relnamespace = 'kernel'::regnamespace and not t.tgisinternal
     and (p.pronamespace <> 'kernel'::regnamespace or pg_get_userbyid(p.proowner) <> 'kk_owner')),
  'every trigger on a kernel table runs a kernel-owned kernel function');
select public.check(not exists (
  select 1 from pg_proc p join pg_language l on l.oid = p.prolang
   where p.pronamespace = 'kernel'::regnamespace
     and (pg_get_userbyid(p.proowner) <> 'kk_owner' or l.lanname not in ('sql', 'plpgsql'))),
  'kernel functions are owned by the kernel and written in SQL or PL/pgSQL');
select public.check(not exists (
  select 1 from pg_proc p
   where p.pronamespace = 'kernel'::regnamespace and p.prosecdef
     and not exists (select 1 from unnest(coalesce(p.proconfig, '{}')) c where c like 'search_path=%')),
  'security definer kernel functions pin their search path');
select public.check(not exists (
  select 1 from pg_depend d
   where d.deptype = 'e'
     and ((d.classid = 'pg_proc'::regclass and d.objid in (select oid from pg_proc where pronamespace = 'kernel'::regnamespace))
       or (d.classid = 'pg_class'::regclass and d.objid in (select oid from pg_class where relnamespace = 'kernel'::regnamespace)))),
  'no extension owns anything in the kernel schema');
select public.check(not exists (
  select 1 from pg_depend d
    join pg_proc p on p.oid = d.refobjid
   where d.refclassid = 'pg_proc'::regclass
     and p.pronamespace not in ('kernel'::regnamespace, 'pg_catalog'::regnamespace)
     and ((d.classid = 'pg_attrdef'::regclass
           and (select adrelid from pg_attrdef where oid = d.objid) in (select oid from pg_class where relnamespace = 'kernel'::regnamespace))
       or (d.classid = 'pg_constraint'::regclass
           and exists (select 1 from pg_constraint k where k.oid = d.objid
                         and (k.conrelid in (select oid from pg_class where relnamespace = 'kernel'::regnamespace)
                              or k.contypid in (select a.atttypid from pg_attribute a join pg_class c on c.oid = a.attrelid
                                                 where c.relnamespace = 'kernel'::regnamespace))))
       or (d.classid = 'pg_policy'::regclass
           and (select polrelid from pg_policy where oid = d.objid) in (select oid from pg_class where relnamespace = 'kernel'::regnamespace))
       or (d.classid = 'pg_rewrite'::regclass
           and (select ev_class from pg_rewrite where oid = d.objid) in (select oid from pg_class where relnamespace = 'kernel'::regnamespace)))),
  'defaults, constraints, policies and rules on kernel tables call only kernel functions');
select public.check(not exists (
  select 1 from pg_proc p, regexp_matches(p.prosrc, '([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\s*\(', 'g') m
   where p.pronamespace = 'kernel'::regnamespace and lower(m[1]) not in ('kernel', 'pg_catalog')),
  'kernel functions call no function outside the kernel by name');
select public.check(not exists (
  select 1 from pg_roles r
   where r.rolname <> 'kk_owner' and not r.rolsuper
     and has_schema_privilege(r.oid, 'kernel', 'CREATE')),
  'only the kernel owner can create objects in the kernel schema');
create function public.t_hook() returns trigger language plpgsql as $$ begin return new; end $$;
grant execute on function public.t_hook() to public;
set role t_extractor;
select public.expect_error($$create trigger t_hook after insert on kernel.claim
                              for each row execute function public.t_hook()$$, '42501');
reset role;
select public.check(true, 'an agent cannot attach a trigger to a kernel table');


\o
select 'ALL KERNEL TESTS PASSED' as result;
