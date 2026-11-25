"""Convert the rebuild 6 map (lists/) to a Backstage catalog, printing the demo's catalog-info.yaml.

    python rebuild-6-map/to_cells.py > catalog-info.yaml

Systems and slots become Components (an API for each interface), nested with `subcomponentOf`: each slot
sits in its system, and each subsystem in the slot of `cmc` it fills. A name with a slash (`wm/buffer-goal`)
is the entity `buffer-goal` in the namespace `wm`, which is how Backstage writes it; Morphogen names the cell
the same way. Links become interfaces, one per slot others use: `talks_through` and `read_by`
consume it, `written_by` (slots only) consume it too. What does not carry over:

- `next` links (the cycle's order of phases): sequence, not an interface;
- the 24 parameters: they are `set_in: spec`, with no file yet, so they cannot be `change` entries;
- components, types and sources: the catalog's business, not the structure's.
"""

import json
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent / "lists"
FILLS = {"cycle": "cmc/cycle", "dm": "cmc/declarative-memory", "learn": "cmc/learning", "motor": "cmc/motor",
         "percept": "cmc/perception", "pm": "cmc/procedural-memory", "wm": "cmc/working-memory"}


def load(name):
    return [json.loads(line) for line in (HERE / f"{name}.jsonl").read_text().splitlines() if line.strip()]


systems, slots = load("systems"), {s["id"]: s for s in load("slots")}
cells, interfaces = {}, {}
for s in systems:
    cells[s["id"]] = {"in": FILLS.get(s["id"]), "description": s["description"]}
for sid, s in slots.items():
    cells[sid] = {"in": s["system"], "description": s.get("interface") or s.get("cmc_module", "")}


def use(interface, user):
    if user in slots and user != interface:
        interfaces.setdefault(interface, [])
        cells[user].setdefault("consumes", [])
        if interface not in cells[user]["consumes"]:
            cells[user]["consumes"].append(interface)


for sid, s in slots.items():
    links = s.get("links") or {}
    if links.get("talks_through"):
        use(links["talks_through"], sid)
    for user in links.get("read_by", []) + links.get("written_by", []):
        use(sid, user)
for i in interfaces:
    cells[i]["provides"] = i
for c in cells.values():
    if c.get("in") is None:
        c.pop("in", None)


def ref(name):
    """A reference with its namespace written out: Backstage reads a bare name in the referrer's own namespace."""
    return name if "/" in name else f"default/{name}"


def entity(kind, name, spec=None, description=None):
    ns, _, short = name.rpartition("/")
    md = {"name": short, **({"namespace": ns} if ns else {}), **({"description": description} if description else {})}
    return {"apiVersion": "backstage.io/v1alpha1", "kind": kind, "metadata": md, "spec": spec or {}}


docs = []
for name, c in cells.items():
    spec = {"type": "service", **({"subcomponentOf": ref(c["in"])} if c.get("in") else {})}
    if c.get("provides"):
        spec["providesApis"] = [ref(c["provides"])]
    if c.get("consumes"):
        spec["consumesApis"] = [ref(x) for x in c["consumes"]]
    docs.append(entity("Component", name, spec, c.get("description")))
docs += [entity("API", name, {"type": "slot"}) for name in interfaces]
yaml.safe_dump_all(docs, sys.stdout, sort_keys=False, width=110)
