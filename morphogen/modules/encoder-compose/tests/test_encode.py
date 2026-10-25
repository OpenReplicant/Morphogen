"""encoder-compose: podinfo's compose file as a topology, each fact citing its line; then recorded, answered
from the record, and superseded when the file changes.

  PGHOST=... PGUSER=<superuser> python3 tests/test_encode.py
"""
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "modules"),
                 str(ROOT / "kernel" / "providers" / "validator-shacl")]
import importlib  # noqa: E402
import install  # noqa: E402  (morphogen/modules/install.py)
from encoder_compose import encode  # noqa: E402
from encoder_compose.__main__ import answer, propose_adopt, scan  # noqa: E402
from kk.lib import connect  # noqa: E402

validator = importlib.import_module("validator.__main__")

DB = "kk_encoder_compose_test"
FILE = ROOT / "morphogen" / "intent" / "systems" / "podinfo" / "compose.yaml"
REL = "morphogen/intent/systems/podinfo/compose.yaml"
KKT = encode.KKT


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


def recorded(res: dict) -> dict:
    """The scan's result once the validator has decided its change set."""
    with connect("kkm_validator") as val:
        validator.drain(val)
        res["status"] = val.execute("select status from api.change_sets where id = %s", (res["change_set"],)).fetchone()[0]
    return res


def line_of(text: str, needle: str, after: str = "") -> int:
    lines = text.splitlines()
    start = next(i for i, x in enumerate(lines) if after in x) if after else 0
    return next(i for i, x in enumerate(lines) if i >= start and needle in x) + 1


text = FILE.read_text()
ops = encode.compose(REL, text, "podinfo")
at = lambda o: int(o["references"][0]["span"]["value"].removeprefix("line="))
find = lambda s, p, name=None: [o for o in ops if o["subject"] == s and o["predicate"] == p
                                and (name is None or (o.get("qualifiers") or {}).get(KKT + "propertyName") == name)]
FRONT, BACK, REDIS = (encode.node_iri("podinfo", s) for s in ("frontend", "backend", "redis"))
check(find("urn:kk:system:podinfo", encode.RDF_TYPE)[0]["object"] == {"entity": KKT + "ServiceTemplate"}
      and at(find("urn:kk:system:podinfo", encode.RDF_TYPE)[0]) == line_of(text, "services:"),
      "the system is a service template, citing its services: line")
check(all(find(n, KKT + "memberOf")[0]["object"] == {"entity": "urn:kk:system:podinfo"} for n in (FRONT, BACK, REDIS))
      and at(find(BACK, encode.RDF_TYPE)[0]) == line_of(text, "  backend:"),
      "each service is a node template in the system, citing its own key")
img = find(REDIS, KKT + "propertyValue", "image")[0]
check(img["object"]["value"]["@value"].startswith("redis:7.4.2-alpine@sha256:") and at(img) == line_of(text, "image: redis"),
      "a node's image, pinned by digest, citing its image: line")
delay = find(BACK, KKT + "propertyValue", "PODINFO_RANDOM_DELAY_MAX")[0]
check(delay["object"]["value"]["@value"] == "600" and at(delay) == line_of(text, "PODINFO_RANDOM_DELAY_MAX"),
      "an environment setting is a property value named by its variable, citing its line")
links = {(o["subject"], o["object"]["entity"]): at(o) for o in ops if o["predicate"] == KKT + "connectsTo"}
check(set(links) == {(FRONT, BACK), (BACK, REDIS)},
      "who connects to whom: the frontend to the backend, the backend to Redis, nothing else")
check(links[(FRONT, BACK)] == line_of(text, "--backend-url", "  frontend:"),
      "a URL in the command naming another service is a connection (cited where it is written, before depends_on)")
check(all(o["evidence_type"] == "deterministic" and o["references"][0]["source_uri"] == f"file:{REL}" for o in ops),
      "every claim is deterministic and cites the compose file")
listed = encode.compose("c.yaml", "services:\n  a:\n    environment:\n      - URL=http://b:80/x\n  b:\n    depends_on:\n      a:\n        condition: service_started\n", "s")
check({(o["subject"], o["object"]["entity"]) for o in listed if o["predicate"] == KKT + "connectsTo"}
      == {("urn:kk:node:s:a", "urn:kk:node:s:b"), ("urn:kk:node:s:b", "urn:kk:node:s:a")}
      and any((o.get("qualifiers") or {}).get(KKT + "propertyName") == "URL" for o in listed),
      "list-form environment and long-form depends_on are read too")
for bad in ("services:\n  Bad Name:\n    image: x\n", "version: '3'\n"):
    try:
        encode.compose("c.yaml", bad, "s")
        check(False, "a malformed file is refused")
    except ValueError:
        pass
check(True, "a file without services, or with a service name that cannot be an IRI, is refused")

# Recorded, answered, superseded.
subprocess.run(["dropdb", "--if-exists", DB], check=True)
os.environ.setdefault("KK_LOGIN_PASSWORD", secrets.token_hex(16))
install.install(DB, ["encoder-compose"])
os.environ["DATABASE_URL"] = f"dbname={DB}"
tmp = Path(tempfile.mkdtemp())
try:
    copy = tmp / "systems" / "podinfo" / "compose.yaml"
    copy.parent.mkdir(parents=True)
    shutil.copy(FILE, copy)
    first = recorded(scan("podinfo", copy, tmp))
    check(first["status"] == "applied" and first["claims"] == len(ops), f"scan records the map ({first['claims']} claims)")
    check(scan("podinfo", copy, tmp)["status"] == "unchanged", "the same file again records nothing")
    with connect("kkm_encoder_compose") as conn:
        got = answer(conn, "podinfo")
    back = got["services"]["backend"]
    check(set(got["services"]) == {"frontend", "backend", "redis"}
          and back["settings"]["PODINFO_RANDOM_DELAY_MAX"]["value"] == "600"
          and back["settings"]["PODINFO_RANDOM_DELAY_MAX"]["source"] == [f"file:systems/podinfo/compose.yaml#line={at(delay)}"]
          and [c["node"] for c in got["services"]["frontend"]["connects_to"]] == [BACK]
          and all("belief" in c and c["claim"] for c in back["connects_to"]),
          "the record answers what each service runs, its settings and what it connects to, citing claim, belief and line")
    copy.write_text(copy.read_text().replace('PODINFO_RANDOM_DELAY_MAX: "600"', 'PODINFO_RANDOM_DELAY_MAX: "150"'))
    second = recorded(scan("podinfo", copy, tmp))
    check(second["status"] == "applied" and second["superseded"] == first["claims"], "a changed file supersedes the earlier map")
    with connect("kkm_encoder_compose") as conn:
        now = answer(conn, "podinfo")["services"]["backend"]["settings"]["PODINFO_RANDOM_DELAY_MAX"]["value"]
        old = conn.execute("select count(*) from api.claims where attributed_to = 'urn:kk:agent:encoder-compose' "
                           "and status = 'deprecated'").fetchone()[0]
    check(now == "150" and old == first["claims"], "the answer is the new value; the old claims are kept, superseded")
    import hashlib
    adopt = propose_adopt("podinfo", copy, tmp)
    with connect("kkm_validator") as val:
        validator.drain(val)
    with connect(url=f"dbname={DB}") as su:
        cs = su.execute("select lane, status, ops from kernel.change_set where id = %s", (adopt["change_set"],)).fetchone()
    step = {o["predicate"].rsplit("/", 1)[-1].rsplit("#", 1)[-1]: o for o in cs[2] if o["subject"].endswith(":step:1")}
    check(cs[0] == "review" and cs[1] == "awaiting_review" and adopt["sha256"] == hashlib.sha256(copy.read_bytes()).hexdigest()
          and step["hasSimpleResult"]["object"]["value"]["@value"] == adopt["sha256"]
          and step["type"]["object"]["entity"] == "urn:kk:action:adopt-system"
          and step["hasFeatureOfInterest"]["object"]["entity"] == "urn:kk:system:podinfo"
          and all(o["references"][0]["source_uri"] == f"file:systems/podinfo/compose.yaml#sha256={adopt['sha256']}" for o in cs[2]),
          "--adopt: a plan asking a person to approve the file as it is, naming its sha256, waits in the review lane (T26)")
    check(propose_adopt("podinfo", copy, tmp)["change_set"] == adopt["change_set"], "--adopt on the same file again submits nothing new")
finally:
    shutil.rmtree(tmp, ignore_errors=True)
    subprocess.run(["dropdb", "--force", DB], check=True)
print("encoder-compose tests passed")
