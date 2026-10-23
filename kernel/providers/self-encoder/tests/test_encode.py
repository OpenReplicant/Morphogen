"""encode.py without a database: claims and the lines they cite.

  python3 kernel/providers/self-encoder/tests/test_encode.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from self_encoder import encode  # noqa: E402

BLUEPRINT = """version: 0.1.0
slots:
  - id: store
    interface: Store
    default: store-pg
    status: ported
  - id: helper
    cardinality: many
    interface: Helper
    default: none
    why: >-
      Nobody needs it yet.
"""
PROVIDER = """id: urn:kk:provider:store-pg
name: Store on Postgres
version: 1.2.3
license: Apache-2.0
slots: [store]
"""
checks = []


def check(name, ok):
    checks.append(bool(ok))
    print(("ok  " if ok else "FAIL"), name)


ops = encode.blueprint("bp.yaml", BLUEPRINT)
by = {(o["subject"], o["predicate"]): o for o in ops}
line = lambda o: o["references"][0]["span"]["value"]   # noqa: E731
check("a slot is typed, labelled, with contract and cardinality (default one), citing its `- id` line",
      by[("urn:kk:slot:store", encode.RDF_TYPE)]["object"] == {"entity": encode.KK + "Slot"}
      and by[("urn:kk:slot:store", encode.KK + "cardinality")]["object"]["value"]["@value"] == "one"
      and by[("urn:kk:slot:store", encode.KK + "slotContract")]["object"]["value"]["@value"] == "Store"
      and line(by[("urn:kk:slot:store", encode.LABEL)]) == "line=3")
check("the default provider is noted, citing its `default:` line",
      by[("urn:kk:slot:store", encode.COMMENT)]["object"]["value"]["@value"] == "Default provider: store-pg (status ported)."
      and line(by[("urn:kk:slot:store", encode.COMMENT)]) == "line=5")
check("an unfilled slot says why, citing its `why:` line",
      by[("urn:kk:slot:helper", encode.COMMENT)]["object"]["value"]["@value"] == "Unfilled: no default provider. Nobody needs it yet."
      and line(by[("urn:kk:slot:helper", encode.COMMENT)]) == "line=11")
check("every claim is deterministic and references its file", all(
      o["evidence_type"] == "deterministic" and o["references"][0]["source_uri"] == "file:bp.yaml" for o in ops))
p = {o["predicate"]: o for o in encode.provider("p/provider.yaml", PROVIDER, "store-pg")}
check("a provider fills its slots, citing its `slots:` line; version and SPDX licence",
      p[encode.KK + "fills"]["object"] == {"entity": "urn:kk:slot:store"} and line(p[encode.KK + "fills"]) == "line=5"
      and p[encode.LICENSE]["object"] == {"entity": "https://spdx.org/licenses/Apache-2.0"}
      and p[encode.VERSION]["object"]["value"]["@value"] == "1.2.3")
print(f"self-encoder checks passed ({sum(checks)}/{len(checks)})" if all(checks) else "self-encoder checks FAILED")
sys.exit(0 if all(checks) else 1)
