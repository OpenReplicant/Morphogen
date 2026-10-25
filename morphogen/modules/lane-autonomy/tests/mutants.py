"""Mutants the kernel's lane-policy case set (kernel/contract/slots/lane-policy) must kill (kernel/contract/mutants.py,
`sh morphogen/contract/run.sh --mutants`). Review forced for plan steps and plans is checked end to end in
morphogen/tests/test_loop.py, which no mutant run reaches."""
ADD = ("set value = kernel.setting.value || (select", "set value = (select")
MUTANTS = [
    ("replaces the store's review rules instead of adding to them", "migration.sql", [ADD]),
    ("mappings no longer reviewed", "migration.sql", [("reset role;", """update kernel.setting set value = value - 'skos:exactMatch'
 where key = 'review_predicates';
reset role;""")]),
    ("nothing reviewed", "migration.sql", [("reset role;", """update kernel.setting set value = '[]'
 where key in ('review_predicates', 'review_types');
reset role;""")]),
]
