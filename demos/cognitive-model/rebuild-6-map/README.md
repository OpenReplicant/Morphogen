# The CMC map, in rebuild 6's format

`build_map.py` writes `lists/` (systems, slots, types, sources, components, parameters) in the
list format of the `rebuild-6` branch, where it was mounted into a scratch Morphogen project as
`cmc`: 160 entries, 63 slots, 24 parameters. Kept as the record of what mapping the spec found;
the new Morphogen reads points, not these lists.

    mkdir -p lists && python build_map.py lists
