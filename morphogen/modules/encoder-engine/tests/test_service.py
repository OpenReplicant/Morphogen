"""encoder-engine against a real engine and record (R5-49): a small system runs from its compose file; its templates
(encoder-compose) and what runs (this encoder) agree, so the kernel's gap finder asks about no drift; restarted with
a setting the file does not have, the running node is drift-modified; stopped, its representations are retracted and
the drift closes. Needs Docker (or Podman as KK_ENGINE) and the redis image podinfo pins.

  PGHOST=... PGUSER=<superuser> python3 tests/test_service.py
"""
import importlib
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
                str(ROOT / "morphogen" / "modules" / "encoder-compose"), str(ROOT / "kernel" / "providers" / "gaps-shacl"),
                str(ROOT / "kernel" / "providers" / "validator-shacl")]
import install  # noqa: E402  (morphogen/modules/install.py)
from encoder_compose.__main__ import scan as scan_compose  # noqa: E402
from encoder_engine.__main__ import AGENT, inspect, record  # noqa: E402
from gaps_shacl.__main__ import one_pass  # noqa: E402
from kk.lib import connect  # noqa: E402

validator = importlib.import_module("validator.__main__")

DB = "kk_encoder_engine_test"
ENGINE = os.environ.get("KK_ENGINE", "docker")
PROJECT, SYSTEM = "kk-drifty", "drifty"
IMG = "redis:7.4.2-alpine@sha256:02419de7eddf55aa5bcf49efb74e88fa8d931b4d77c07eff8a6b2144472b6952"
FILE = f"""services:
  cache:
    image: {IMG}
    command: ["redis-server", "--save", ""]
    environment:
      LOG: info
"""
OA = "http://www.w3.org/ns/oa#"


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg, flush=True)


def settle():
    with connect("kkm_validator") as val:
        validator.drain(val)


def compose(text: str, *args: str):
    f = tmp / "compose.yaml"
    f.write_text(text)
    return subprocess.run([ENGINE, "compose", "-p", PROJECT, "-f", str(f), *args], capture_output=True, text=True, timeout=300)


def drift() -> list[tuple[str, str]]:
    with connect("kkm_gaps_shacl") as conn:
        one_pass(conn)
    settle()
    with connect("kkm_gaps_shacl") as conn:
        rows = conn.execute(
            "select k.object_entity, t.object_entity from api.claims t join api.claims k on k.subject = t.subject "
            "and k.predicate = 'http://purl.org/dc/terms/type' and k.status <> 'deprecated' "
            "where t.predicate = %s and t.attributed_to = 'urn:kk:agent:gaps-shacl' and t.status <> 'deprecated'",
            (OA + "hasTarget",)).fetchall()
    return sorted((k.rsplit(":", 1)[-1], t) for k, t in rows if "drift" in k)


def engine_scan() -> dict:
    out = record(SYSTEM, PROJECT, inspect(PROJECT), FILE)
    settle()
    return out


if subprocess.run([ENGINE, "info"], capture_output=True).returncode != 0:
    print(f"skipped: no {ENGINE} engine")
    sys.exit(0)
subprocess.run(["dropdb", "--if-exists", DB], check=True)
os.environ.setdefault("KK_LOGIN_PASSWORD", secrets.token_hex(16))
install.install(DB, ["encoder-compose", "encoder-engine"])
os.environ["DATABASE_URL"] = f"dbname={DB}"
tmp = Path(tempfile.mkdtemp())
try:
    up = compose(FILE, "up", "-d", "--pull", "never")
    check(up.returncode == 0, f"the system runs ({up.stderr.strip()[-200:]})")
    (tmp / "systems" / SYSTEM).mkdir(parents=True)
    (tmp / "systems" / SYSTEM / "compose.yaml").write_text(FILE)
    scan_compose(SYSTEM, tmp / "systems" / SYSTEM / "compose.yaml", tmp)
    settle()
    first = engine_scan()
    with connect("kkm_encoder_engine") as conn:
        applied = conn.execute("select status from api.change_sets where id = %s", (first["change_set"],)).fetchone()[0]
    check(first["claims"] > 0 and applied == "applied", f"what runs is recorded as node representations ({first}, {applied})")
    check(engine_scan()["status"] == "unchanged", "the same view again records nothing")
    check(drift() == [], "templates and what runs agree: no drift")

    restarted = compose(FILE.replace("LOG: info", "LOG: debug"), "up", "-d", "--pull", "never")
    check(restarted.returncode == 0, "the system restarted with another setting than its compose file says")
    again = engine_scan()
    check(again["superseded"] > 0, f"the new view supersedes the old ({again})")
    check(drift() == [("drift-modified", f"urn:kk:representation:{SYSTEM}:cache")],
          "the running node's setting differs from its template's: drift-modified")
    with connect("kkm_encoder_engine") as conn:
        seen = {r[0] for r in conn.execute("select object_value->>'@value' from api.claims where attributed_to = %s", (AGENT,))}
    check("debug" not in seen, "the value set outside the compose file is withheld, never recorded")

    compose(FILE, "down")
    gone = engine_scan()
    with connect("kkm_encoder_engine") as conn:
        left = conn.execute("select count(*) from api.claims where attributed_to = %s and status <> 'deprecated'", (AGENT,)).fetchone()[0]
    check(gone["claims"] == 0 and left == 0, "stopped: its representations are retracted (kept, not deleted)")
    check(drift() == [], "and the drift closes; a system nothing of runs has none")
finally:
    compose(FILE, "down", "-v")
    shutil.rmtree(tmp, ignore_errors=True)
    subprocess.run(["dropdb", "--force", DB], check=True)
print("encoder-engine service tests passed")
