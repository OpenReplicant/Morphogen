# The CMC map, in rebuild 6's format

`build_map.py` writes `lists/` (systems, slots, types, sources, components, parameters) in the
list format of the `rebuild-6` branch, where it was mounted into a scratch Morphogen project as
`cmc`: 160 entries, 63 slots, 24 parameters. Kept as the record of what mapping the spec found;
Morphogen now reads the cell format: `python rebuild-6-map/to_cells.py > morphogen.yaml` converts
these lists to the demo's `morphogen.yaml` (what does not carry over is listed in the script).

    mkdir -p lists && python build_map.py lists
