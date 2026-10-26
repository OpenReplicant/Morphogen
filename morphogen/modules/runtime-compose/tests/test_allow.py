"""The runtime allow list (`morphogen.runtime.refusal`, every runtime's): podinfo's file passes; anything that could reach the host, or our own
environment, is refused. No database, no Docker (the runtime case set checks what runs: morphogen/contract/slots/runtime).

  python3 tests/test_allow.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "morphogen" / "src"), str(ROOT / "kernel" / "src")]
from morphogen.runtime import DIGEST, refusal  # noqa: E402

PODINFO = ROOT / "morphogen" / "intent" / "systems" / "podinfo" / "compose.yaml"
IMG = "redis:7.4.2-alpine@sha256:" + "0" * 64


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def svc(**kw):
    return "services:\n  a:\n" + "".join(f"    {k}: {v}\n" for k, v in {"image": IMG, **kw}.items())


check(refusal(PODINFO.read_text()) is None, "podinfo's compose file is on the allow list")
from rdflib import Graph, Namespace  # noqa: E402
SH, KKTS = Namespace("http://www.w3.org/ns/shacl#"), Namespace("https://w3id.org/knowledge-kernel/tosca/shapes#")
shapes = Graph().parse(ROOT / "kernel" / "packs" / "kk-tosca.shapes.ttl", format="turtle")
pins = {str(p) for prop in shapes.objects(KKTS.PinnedImageSetting, SH.property) for p in shapes.objects(prop, SH.pattern)}
check(pins == {f"^{DIGEST.pattern}$"}, f"the gap finder asks for a pin exactly as the runtime requires one: {pins}")
for text, why in [(svc(privileged="true"), "privileged not allowed"), (svc(volumes='["/:/host"]'), "volumes not allowed"),
                  (svc(build="."), "build not allowed"), (svc(env_file="/etc/shadow"), "env_file not allowed"),
                  (svc(network_mode="host"), "network_mode not allowed"), (svc(cap_add="[SYS_ADMIN]"), "cap_add not allowed"),
                  (svc(extends="{file: x.yaml, service: b}"), "extends not allowed"),
                  ("services:\n  a:\n    image: redis:7.4.2-alpine\n", "pinned by digest"),
                  (svc(ports='["9898:9898"]'), "127.0.0.1"), (svc(ports='["0.0.0.0:1:2"]'), "127.0.0.1"),
                  (svc(environment="{A: ${HOME}}"), "no $"), (svc(environment="[DOCKER_HOST]"), "a name alone"),
                  (svc(environment="{HOME: }"), "a name alone"), (svc(**{"1": "x"}), "1 not allowed"), (svc() + "volumes: {x: {}}\n", "nothing else at the top"),
                  ("include: [x.yaml]\nservices: {}\n", "nothing else at the top"), ("services:\n  A B: {image: x}\n", "lower-case"),
                  (svc(depends_on='["db"]'), "depends_on names only other services"),
                  (svc(depends_on='["a"]'), "depends_on names only other services"),
                  (svc(depends_on='["b\\n[Service]\\nExecStartPre=/bin/sh"]') + "  b:\n    image: " + IMG + "\n", "depends_on names only other services"),
                  (svc(depends_on="{b: {condition: service_started, restart: true}}") + "  b:\n    image: " + IMG + "\n", "only condition"),
                  (svc(healthcheck='"x"'), "healthcheck must be a mapping"), (svc(healthcheck="{test: x, start_interval: 1s}"), "healthcheck must be a mapping"),
                  (svc(restart="sometimes"), "restart must be one of"),
                  (svc(image="reg%H/x@sha256:" + "0" * 64), "pinned by digest")]:
    got = refusal(text)
    check(got is not None and why in got, f"refused: {why} ({text.splitlines()[-1].strip()[:40]})")
ok = svc(depends_on="{b: {condition: service_healthy}}", healthcheck="{test: [CMD, true], interval: 5s}", restart="always") \
    + "  b:\n    image: " + IMG + "\n"
check(refusal(ok) is None, "depends_on on another service (list or condition), a healthcheck mapping and a known restart pass")
print("runtime-compose allow list tests passed")
