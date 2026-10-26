"""encoder-engine without an engine or a database (R5-49): `inspect` output for a compose project becomes node
representations in the terms encoder-compose gives templates; together with a template map, the kernel's gap finder
finds no drift when they agree and drift-modified when a setting differs.

  python3 tests/test_encode.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "morphogen" / "modules" / "encoder-compose"), str(ROOT / "kernel" / "providers" / "gaps-shacl"),
                str(ROOT / "kernel" / "src")]
from encoder_compose import encode as compose  # noqa: E402
from encoder_engine import encode  # noqa: E402
from gaps_shacl.gaps import gaps, shapes  # noqa: E402

KKT = encode.KKT
IMG = "redis:7.4.2-alpine@sha256:02419de7eddf55aa5bcf49efb74e88fa8d931b4d77c07eff8a6b2144472b6952"


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def container(name, service, project="kk-shop", running=True, env=("LOG=info",), cmd=("redis-server",)):
    return {"Id": f"{name}0123456789", "Name": f"/{name}", "State": {"Running": running},
            "Config": {"Image": IMG, "Cmd": list(cmd), "Env": list(env) + ["PATH=/usr/bin"],
                       "Labels": {encode.PROJECT: project, encode.SERVICE: service}}}


def as_claims(ops, tag):
    return [{"id": f"{tag}{i}", "subject": o["subject"], "predicate": o["predicate"], "object_entity": o["object"].get("entity"),
             "object_value": o["object"].get("value"), "qualifiers": o.get("qualifiers") or {}}
            for i, o in enumerate(ops) if o["op"] == "add_claim"]


ops = encode.representations("shop", "kk-shop", [container("shop-cache-2", "cache"), container("shop-cache-1", "cache"),
                                                 container("shop-old-1", "old", running=False),
                                                 container("blog-cache-1", "cache", project="kk-blog")])
subjects = {o["subject"] for o in ops}
props = {o["qualifiers"][KKT + "propertyName"]: o["object"]["value"]["@value"] for o in ops if o["predicate"] == KKT + "propertyValue"}
check(subjects == {"urn:kk:representation:shop:cache"}, "one representation per running service of the project; a stopped container and another project give nothing")
check({(o["predicate"], (o["object"].get("entity") or "")) for o in ops} >= {
    ("http://www.w3.org/1999/02/22-rdf-syntax-ns#type", KKT + "NodeRepresentation"), (KKT + "memberOf", "urn:kk:system:shop"),
    (KKT + "representationOf", "urn:kk:node:shop:cache")}, "it is a node representation of its template, in its system")
check(props == {"image": IMG, "command": encode.WITHHELD, "LOG": encode.WITHHELD, "PATH": encode.WITHHELD},
      f"with no compose file to compare with, the image as written and every other setting withheld: {props}")
check(all(o["evidence_type"] == "observed" and o["references"][0]["source_uri"] == "urn:kk:engine:docker:container:shop-cache-10123456789"
          for o in ops), "every claim is observed and cites the container it was read from (the first by name)")

text = f"""services:
  cache:
    image: {IMG}
    command: ["redis-server"]
    environment:
      LOG: info
"""
template = as_claims(compose.compose("shop.yaml", text, "shop"), "t")
intended = encode.declared(text)
ops = encode.representations("shop", "kk-shop", [container("shop-cache-1", "cache")], intended=intended)
props = {o["qualifiers"][KKT + "propertyName"]: o["object"]["value"]["@value"] for o in ops if o["predicate"] == KKT + "propertyValue"}
check(props == {"image": IMG, "command": "redis-server", "LOG": "info", "PATH": encode.WITHHELD},
      f"what the compose file declares is recorded as it runs; a setting it does not declare is withheld: {props}")
secret = encode.representations("shop", "kk-shop", [container("shop-cache-1", "cache", env=("LOG=info", "DB_PASSWORD=hunter2"),
                                                              cmd=("redis-server", "--requirepass", "s3cret"))], intended=intended)
check(not any(v in str(secret) for v in ("hunter2", "s3cret")), "a password set where it runs, in its environment or its command, never reaches the record")
check(encode.declared('services:\n  cache:\n    command: redis-server --save ""\n')["cache"]["command"] == "redis-server --save ",
      "a string command is split as a shell splits it, as the engine runs it")
rules = shapes()
drift = lambda running: sorted((g["kind"].rsplit(":", 1)[-1], g["target"]) for g in gaps(template + as_claims(running, "r"), rules)  # noqa: E731
                               if "drift" in g["kind"])
check(drift(ops) == [], "what runs as its compose file says: no drift")
debug = encode.representations("shop", "kk-shop", [container("shop-cache-1", "cache", env=("LOG=debug",))], intended=intended)
check(drift(debug) == [("drift-modified", "urn:kk:representation:shop:cache")], "a setting changed where it runs: drift-modified")
check(drift([]) == [], "a system nothing of runs: no drift")
try:
    encode.representations("Shop!", "kk-shop", [])
    check(False, "a bad system name is refused")
except ValueError:
    check(True, "a bad system name is refused")
print("encoder-engine encode tests passed")
