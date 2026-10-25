"""runtime-compose's allow list (`refusal`): podinfo's file passes; anything that could reach the host, or our own
environment, is refused. No database, no Docker (the runtime case set checks what runs: morphogen/contract/slots/runtime).

  python3 tests/test_allow.py
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "morphogen" / "src"), str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "modules" / "map-gaps")]
from map_gaps import gaps  # noqa: E402
from runtime_compose.__main__ import DIGEST, refusal  # noqa: E402

PODINFO = ROOT / "morphogen" / "intent" / "systems" / "podinfo" / "compose.yaml"
IMG = "redis:7.4.2-alpine@sha256:" + "0" * 64


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def svc(**kw):
    return "services:\n  a:\n" + "".join(f"    {k}: {v}\n" for k, v in {"image": IMG, **kw}.items())


check(refusal(PODINFO.read_text()) is None, "podinfo's compose file is on the allow list")
check(gaps.DIGEST.pattern == DIGEST.pattern, "the gap finder asks for a pin exactly as the runtime requires one")
for text, why in [(svc(privileged="true"), "privileged not allowed"), (svc(volumes='["/:/host"]'), "volumes not allowed"),
                  (svc(build="."), "build not allowed"), (svc(env_file="/etc/shadow"), "env_file not allowed"),
                  (svc(network_mode="host"), "network_mode not allowed"), (svc(cap_add="[SYS_ADMIN]"), "cap_add not allowed"),
                  (svc(extends="{file: x.yaml, service: b}"), "extends not allowed"),
                  ("services:\n  a:\n    image: redis:7.4.2-alpine\n", "pinned by digest"),
                  (svc(ports='["9898:9898"]'), "127.0.0.1"), (svc(ports='["0.0.0.0:1:2"]'), "127.0.0.1"),
                  (svc(environment="{A: ${HOME}}"), "no $"), (svc(environment="[DOCKER_HOST]"), "a name alone"),
                  (svc(environment="{HOME: }"), "a name alone"), (svc(**{"1": "x"}), "1 not allowed"), (svc() + "volumes: {x: {}}\n", "nothing else at the top"),
                  ("include: [x.yaml]\nservices: {}\n", "nothing else at the top"), ("services:\n  A B: {image: x}\n", "lower-case")]:
    got = refusal(text)
    check(got is not None and why in got, f"refused: {why} ({text.splitlines()[-1].strip()[:40]})")
print("runtime-compose allow list tests passed")
