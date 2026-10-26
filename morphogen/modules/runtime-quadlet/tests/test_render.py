"""runtime-quadlet's rendering: an approved compose file becomes Quadlet units that run what the file says. No database,
no systemd (the runtime case set checks which file runs: morphogen/contract/slots/runtime).

  python3 tests/test_render.py

Checks that the case set's reading of a `.quadlets` bundle (runner.py `model`) gives back every allow-listed key of
the compose file; that Podman's own Quadlet generator, when installed, turns the units into a `podman run` whose
words are the file's values (quoting and `%` included); that values a unit cannot hold are refused; and the calls
made to the engine.
"""
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(ROOT / "morphogen" / "src"), str(ROOT / "kernel" / "src"),
                str(ROOT / "morphogen" / "contract" / "slots" / "runtime")]
from runtime_quadlet.__main__ import Quadlet, bundle, render  # noqa: E402
from runner import model  # noqa: E402
from morphogen.runtime import refusal  # noqa: E402

PODINFO = ROOT / "morphogen" / "intent" / "systems" / "podinfo" / "compose.yaml"
IMG = "docker.io/library/redis@sha256:" + "0" * 64
GENERATOR = next((p for p in ("/usr/libexec/podman/quadlet", "/usr/lib/podman/quadlet", "/usr/local/libexec/podman/quadlet")
                  if os.access(p, os.X_OK)), None)
EVERY = f"""services:
  web:
    image: {IMG}
    command: ["--port", "98 98", "%n", "a\\\\b", 'say "hi"']
    entrypoint: ["/bin/sh", "-c"]
    environment:
      PLAIN: "600"
      SPACED: "v a % \\" x \\\\ y"
    ports: ["127.0.0.1:8080:9898", "127.0.0.1::53/udp"]
    labels: {{"a": "b c", "pct": "50%"}}
    working_dir: /srv x%n
    user: "1000"
    healthcheck: {{test: ["CMD", "curl", "-f", "http://localhost:9898/healthz"], interval: 10s, retries: 3}}
    restart: unless-stopped
    depends_on: [cache]
  cache:
    image: {IMG}
    command: redis-server --save ""
"""


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def generate(units: dict[str, str]) -> tuple[int, str]:
    with tempfile.TemporaryDirectory() as d:
        for name, body in units.items():
            Path(d, name).write_text(body)
        out = subprocess.run([GENERATOR, "-dryrun", "-user"], env={**os.environ, "QUADLET_UNIT_DIRS": d},
                             capture_output=True, text=True)
        return out.returncode, out.stdout + out.stderr


def specifiers(word: str) -> str:
    """A word of a generated ExecStart as systemd runs it: `%%` is `%`, any other `%c` a specifier systemd fills in
    (shown as `<%c>`, so a value whose `%` was not doubled no longer equals itself)."""
    return re.sub(r"%(.)", lambda m: "%" if m.group(1) == "%" else f"<%{m.group(1)}>", word)


def podman_version() -> tuple[int, ...]:
    out = subprocess.run(["podman", "--version"], capture_output=True, text=True) if shutil.which("podman") else None
    m = re.search(r"(\d+)\.(\d+)", out.stdout if out else "")
    return tuple(int(x) for x in m.groups()) if m else (0, 0)


check(refusal(EVERY) is None, "the test file uses every key on the allow list and passes it")
for text, label in ((PODINFO.read_text(), "podinfo's compose file"), (EVERY, "a file with every allowed key")):
    units = render("kk-demo", text.encode())
    check(model(bundle(units)) == model(text), f"{label}: the units hold what the file says, read back as the case set reads them")

units = render("kk-demo", EVERY.encode())
web = units["kk-demo-web.container"]
check("Network=kk-demo.network" in web and "NetworkAlias=web" in web and "ContainerName=kk-demo-web" in web
      and units["kk-demo.network"] == "[Network]\n", "each service joins the system's own network under its service name")
check("Requires=kk-demo-cache.service" in web and "After=kk-demo-cache.service" in web and "Restart=always" in web
      and "WantedBy=default.target" in web, "depends_on, restart and starting at boot become unit settings")
check('HealthCmd=["curl", "-f", "http://localhost:9898/healthz"]' in web and "HealthRetries=3" in web,
      "a healthcheck becomes Quadlet's health settings, unquoted")

for bad, why in (("a\nb", "a line break"), ("x\\", "a trailing backslash")):
    text = EVERY.replace("working_dir: /srv x%n", f"working_dir: {json.dumps(bad)}")
    try:
        render("kk-demo", text.encode())
        check(False, f"{why} in a value is refused")
    except ValueError:
        check(True, f"{why} in a value is refused")

# render's own checks, for a file that reached it without the allow list (each runtime keeps its own format safe)
for deps, why in (('["cache\\n[Service]\\nExecStartPre=/bin/touch /tmp/x"]', "a line break and a unit section"),
                  ('["cache\\n---\\n# FileName=evil.container"]', "a second file in the bundle"),
                  ('["db"]', "a service the file does not have")):
    text = f"services:\n  web:\n    image: {IMG}\n    depends_on: {deps}\n  cache:\n    image: {IMG}\n"
    try:
        out = bundle(render("kk-demo", text.encode()))
        check(False, f"depends_on naming {why} is refused when rendering: {out[:200]}")
    except ValueError:
        check(True, f"depends_on naming {why} is refused when rendering")
odd = render("kk-demo", f"services:\n  web:\n    image: reg%H/x{IMG[IMG.index('@'):]}\n".encode())["kk-demo-web.container"]
check("Image=reg%%H/x@" in odd, "% in an image reference is doubled, as everywhere")

if GENERATOR:
    version = podman_version()
    gen = dict(units)
    if version < (5, 6):     # older generators lack keys Podman 5.6 has (NetworkAlias, Entrypoint): checked without them
        gen = {n: re.sub(r"(?m)^(NetworkAlias|Entrypoint)=.*\n", "", b) for n, b in gen.items()}
        print(f"note: Podman {'.'.join(map(str, version))} here; NetworkAlias and Entrypoint left out of the generator check")
    rc, out = generate(gen)
    check(rc == 0 and "unsupported key" not in out, f"Podman's Quadlet generator takes the units: {out[-300:] if rc else ''}")
    line = next((l for l in out.splitlines() if l.startswith("ExecStart=") and "--name=kk-demo-web" in l), "")
    args = [specifiers(a) for a in shlex.split(line.removeprefix("ExecStart="))]
    check(["--env", "SPACED=v a % \" x \\ y"] == args[args.index("--env", args.index("--env") + 1):][:2]
          and ["--label", "pct=50%"] == args[args.index("--label", args.index("--label") + 1):][:2]
          and "-w=/srv x%n" in args and args[args.index("--user") + 1] == "1000",
          f"the generated podman run holds each value exactly, spaces, quotes, backslashes and % included: {args}")
    check(args[-5:] == ["--port", "98 98", "%n", "a\\b", 'say "hi"'], f"the command's words reach podman run as they are: {args[-5:]}")
else:
    print("note: no Quadlet generator installed; the generator checks were not run")

with tempfile.TemporaryDirectory() as d:
    log = Path(d, "log")
    for name in ("podman", "systemctl"):
        Path(d, name).write_text(f"#!{sys.executable}\nimport json, os, sys\nopen({str(log)!r}, 'a').write(json.dumps("
                                 "[os.path.basename(sys.argv[0])] + sys.argv[1:] + [open(a).read() for a in sys.argv[1:] if os.path.isfile(a)]) + '\\n')\n")
        Path(d, name).chmod(0o755)
    os.environ["PATH"] = d + os.pathsep + os.environ["PATH"]
    first = "services:\n  web:\n    image: " + IMG + "\n  old:\n    image: " + IMG + "\n"
    second = "services:\n  web:\n    image: " + IMG + "\n"
    out = Quadlet().apply("kk-demo", first.encode(), None)
    calls = [json.loads(x) for x in log.read_text().splitlines()]
    user = [] if os.geteuid() == 0 else ["--user"]
    check(out.returncode == 0 and [c[:5] for c in calls] == [["podman", "quadlet", "install", "--replace", "--application"]] * 1
          + [["systemctl", *user, "restart", "kk-demo-old.service", "kk-demo-web.service"][:5]]
          and calls[0][5] == "kk-demo" and model(calls[0][-1]) == model(first),
          f"the bundle is installed as the project's application, then every service unit restarted: {[c[:6] for c in calls]}")
    log.unlink()
    Quadlet().apply("kk-demo", second.encode(), first.encode())
    calls = [json.loads(x) for x in log.read_text().splitlines()]
    check([c[:3 + len(user)] for c in calls[:2]] == [["systemctl", *user, "stop", "kk-demo-old.service"][:3 + len(user)],
                                                     ["podman", "quadlet", "rm", "--force"][:3 + len(user)]]
          and calls[1][-1] == "kk-demo" and calls[2][2] == "install" and model(calls[2][-1]) == model(second),
          f"a service the new file no longer has is stopped and the application removed before the install: {[c[:5] for c in calls]}")
    log.unlink()
    out = Quadlet().apply("kk-demo", f"services:\n  web:\n    image: {IMG}\n    healthcheck: x\n".encode(), None)
    check(out.returncode != 0 and not log.exists(), f"a malformed healthcheck fails that system's apply, nothing raised: {out.stderr}")
    out = Quadlet().apply("kk-demo", EVERY.replace("/srv x%n", '"/srv\\nx"').encode(), None)
    check(out.returncode != 0 and not log.exists(),
          "a file the units cannot hold fails that system's apply, with nothing handed to the engine")

print("runtime-quadlet render tests passed")
