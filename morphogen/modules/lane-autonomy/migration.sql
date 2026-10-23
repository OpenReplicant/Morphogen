-- Module install: lane-autonomy. Runs once as a superuser; applied by morphogen/modules/install.py.
-- Plan steps (sosa:Actuation) and plans (p-plan:Plan) always take the review lane: the store enforces it
-- (kernel.needs_review, setting review_types), whatever lane the planner asks for (R5-20).
set role kk_owner;
update kernel.setting
   set value = kernel.setting.value || (select coalesce(jsonb_agg(t.iri), '[]'::jsonb)
                         from jsonb_array_elements_text('["http://www.w3.org/ns/sosa/Actuation",
                                                          "http://purl.org/net/p-plan#Plan"]') as t(iri)
                         where not kernel.setting.value ? t.iri)
 where key = 'review_types';
reset role;
