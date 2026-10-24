"""design-blueprint unit checks (R5-29): a described map renders to a compose file that encoder-compose maps
back to the same description; a conflict is refused; the plan names the file's sha256, carries its text, goes
to review and derives from the map claims. No database.

  python3 tests/test_blueprint.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "morphogen" / "src"), str(ROOT / "kernel" / "src"),
                 str(ROOT / "morphogen" / "modules" / "encoder-compose")]
from encoder_compose import encode  # noqa: E402
from morphogen import blueprint  # noqa: E402

from design_blueprint.__main__ import ACTION, plan  # noqa: E402

KKT, T = blueprint.KKT, blueprint.RDF_TYPE
N = "urn:kk:node:notes:"


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


claims = []


def c(s, p, o=None, v=None, name=None):
    claims.append({"id": f"c{len(claims)}", "subject": N + s, "predicate": p, "object_entity": o,
                   "object_value": {"@value": v} if v is not None else None,
                   "qualifiers": {KKT + "propertyName": name} if name else {}})


for svc in ("web", "api", "db"):
    c(svc, T, KKT + "NodeTemplate")
    c(svc, KKT + "memberOf", "urn:kk:system:notes")
c("web", KKT + "connectsTo", N + "api")
c("api", KKT + "connectsTo", N + "db")
c("web", KKT + "propertyValue", v="ghcr.io/example/notes-web:1.4.2", name="image")
c("api", KKT + "propertyValue", v="ghcr.io/example/notes-api:1.4.2", name="image")
c("db", KKT + "propertyValue", v="postgres:16.4", name="image")
c("api", KKT + "propertyValue", v="info", name="LOG_LEVEL")
c("api", KKT + "propertyValue", v="600", name="TIMEOUT_MS")

d = blueprint.described(claims, "notes")
text = blueprint.render(d, "notes")
ops = encode.compose("systems/notes/compose.yaml", text, "notes")
back = [{"id": i, **op, "object_entity": op["object"].get("entity"), "object_value": op["object"].get("value")}
        for i, op in enumerate(ops)]
check(blueprint.described(back, "notes") == d, "the rendered file, mapped by encoder-compose, is the described system")
check(blueprint.render(blueprint.described(list(reversed(claims)), "notes"), "notes") == text,
      "the same description renders the same text, whatever order its claims come in")
check(blueprint.described(claims + [dict(claims[-1], id="dup")], "notes") == d, "the same setting twice is one setting")
for extra, why in [({"subject": N + "api", "predicate": KKT + "propertyValue", "object_value": {"@value": "debug"},
                     "qualifiers": {KKT + "propertyName": "LOG_LEVEL"}}, "two values for one setting"),
                   ({"subject": N + "api", "predicate": KKT + "connectsTo", "object_entity": N + "payments"},
                    "a connection to a service the system does not have")]:
    try:
        blueprint.described(claims + [{"id": "x", "object_entity": None, "object_value": None, "qualifiers": {}, **extra}], "notes")
        check(False, f"{why} is a conflict")
    except blueprint.Conflict:
        check(True, f"{why} is a conflict a person settles first")
cs = plan("notes", text, sorted(x["id"] for x in claims))
get = lambda p: [op["object"] for op in cs["ops"] if op["predicate"] == p]  # noqa: E731
check(cs["lane"] == "review" and get("http://purl.org/dc/terms/type")[1] == {"entity": ACTION}
      and get("http://www.w3.org/ns/sosa/hasSimpleResult") == [{"value": {"@value": blueprint.sha(text)}}]
      and get("http://www.w3.org/ns/sosa/hasFeatureOfInterest") == [{"entity": "urn:kk:system:notes"}],
      "the plan goes to review; its step creates the system and names the file's sha256")
check(text in get("http://www.w3.org/2000/01/rdf-schema#label")[0]["value"]["@value"]
      and all(op["derived_from"] == sorted(x["id"] for x in claims) for op in cs["ops"]),
      "the plan's label is the file's whole text (what a person approves), derived from the map claims")
print("design-blueprint checks passed")
