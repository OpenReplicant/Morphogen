"""Mutants the vocabulary-pack slot's case set (kernel/contract/slots/vocabulary-pack) must kill
(kernel/contract/mutants.py). A pack edited without regenerating packs.sql fails its `pinned` case too."""
EXTRA = ("""\\ir packs.sql""", """\\ir packs.sql
set role kk_owner;
select kernel.install_ops('pack:extra', 'urn:kk:scope:vocab', $kk$[{"op": "add_claim", "subject": "https://w3id.org/knowledge-kernel/ns#notATerm",
  "predicate": "http://www.w3.org/1999/02/22-rdf-syntax-ns#type", "object": {"entity": "http://www.w3.org/2002/07/owl#ObjectProperty"},
  "evidence_type": "deterministic", "references": [{"source_uri": "file:kernel/packs/kk-core.ttl"}]}]$kk$::jsonb,
  'urn:kk:agent:pack-loader', 'urn:kk:module:pack-loader');
reset role;""")
MUTANTS = [
    ("a pack left out", "packs.sql", [("select kernel.install_ops('pack:mappings:0.2.0'",
                                       "select 1 where false and kernel.install_ops('pack:mappings:0.2.0'")]),
    ("a property no pack types is approved", "migration.sql", [EXTRA]),
]
