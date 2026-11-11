"""What a judged run is given beyond its tree (PLAN.md, phase 7b): values from an env file, and services.

A caller's tests may need a database, a service, or settings such as a connection string. The operator names
them in morphogen.local.yaml (or a request's `local`), never in a commit:

    env:
      file: /outside/the/repository/run.env   # KEY=VALUE lines; outside the repository, or there but untracked
      pass: [DATABASE_URL, API_TOKEN]          # the names every run gets as environment variables
      public: [DB_PORT]                        # values that are not secret: not scanned for in a run's output
    services:
      db:                                      # reached by this name from the run
        image: docker.io/library/postgres:17.6
        env: [POSTGRES_PASSWORD]               # names from the file, given to the service (the run gets only `pass`)
        command: [postgres, -c, fsync=off]     # optional
        ready: pg_isready -h 127.0.0.1         # run inside the service until it succeeds
        ready_timeout: 60

What holds, for base and candidate alike:
- The values are read once, before the runs; the verdict records the names and one digest of them all, never a
  value. The file is read again after the runs, and a change refuses the verdict.
- A run that prints a secret value, as it is or in base64, hex or reversed, is refused, and nothing of its
  output reaches the verdict or an error message. A value the scan cannot tell from ordinary output (shorter
  than eight characters) must be called `public`. A run that encodes a value in some other way is not caught
  here; what stops it is that a verdict keeps only clipped output of failures, and the evidence log is the
  operator's.
- Services run only in a container runner. Each run gets its own: started from the image's id (resolved once,
  so a re-tagged image changes nothing mid-verdict), on a network of its own that has nothing else on it and
  no route out, and removed after the run, so nothing one run writes to a service reaches another.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.parse
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .errors import JudgeError

NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SERVICE = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
RESERVED = {"PATH", "HOME", "TMPDIR", "TEMP", "TMP", "IFS", "ENV", "BASH_ENV", "SHELL", "PWD", "USER"}
RESERVED_PREFIXES = ("MORPHOGEN_", "PYTHON", "LD_", "DYLD_", "GIT_")
MIN_SECRET = 8


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Env(_Strict):
    file: str
    pass_: list[str] = Field([], alias="pass")
    public: list[str] = []


class Gateway(_Strict):
    container: str                  # the operator's running gateway, on a bridge network (as compose puts it)
    port: int = 8080
    meter: str                      # `METER open RUN_ID` prints {"env": {...}}; `METER close RUN_ID` prints {"calls": ...}
    meter_timeout: int = 60


class Service(_Strict):
    image: str
    env: list[str] = []
    command: list[str] | str | None = None
    ready: str | None = None
    ready_timeout: int = 60


@dataclass
class Served:
    passed: dict[str, str] = field(default_factory=dict)          # what each run gets
    services: dict[str, dict] = field(default_factory=dict)       # name: {image, id, env: {name: value}, ...}
    secrets: dict[str, str] = field(default_factory=dict)         # name: value, scanned for in every output
    file: Path | None = None
    digest: str | None = None
    gateway: dict | None = None                                   # {container, port, meter, meter_timeout}
    record: dict = field(default_factory=dict)

    def leaks(self, *texts: str, extra: dict[str, str] | None = None) -> list[str]:
        """The names whose value, in a form the scan knows, appears in any of `texts`; `extra`: one run's own
        secrets (what the meter gave it)."""
        out = []
        for name, v in {**self.secrets, **(extra or {})}.items():
            b = v.encode()
            forms = {v, v[::-1], b.hex(), b.hex().upper(), urllib.parse.quote(v, safe=""),
                     base64.b64encode(b).decode().rstrip("="), base64.urlsafe_b64encode(b).decode().rstrip("=")}
            if any(f in t for t in texts if t for f in forms):
                out.append(name)
        return sorted(out)

    @contextmanager
    def session(self, engine: str, memory: str = "1g", cpus: str = "1"):
        """For one run in a container: an env file with the passed values (mode 600, never on a command line);
        when there are services or a gateway, a network of the run's own with fresh services on it and the
        gateway joined to it; and the meter opened for the run. Yields a Session; removes everything
        afterwards and, with a gateway, closes the meter into Session.metered."""
        ses = Session(tag="morphogen-" + secrets.token_hex(6), tmp=Path(tempfile.mkdtemp(prefix="morphogen-served-")))
        started, joined, opened = [], False, False
        try:
            env = dict(self.passed)
            if self.services or self.gateway:
                ses.network = ses.tag
                _engine(engine, "network", "create", "--internal", ses.network)
            for name, s in self.services.items():
                cname = f"{ses.tag}-{name}"
                args = ["run", "-d", "--rm", "--name", cname, "--network", ses.network, "--network-alias", name,
                        "--memory", memory, "--cpus", cpus]
                if s["env"]:
                    args += ["--env-file", str(_env_file(ses.tmp / f"{name}.env", s["env"]))]
                cmd = s["command"]
                args += [s["id"], *(["sh", "-c", cmd] if isinstance(cmd, str) else cmd or [])]
                _engine(engine, *args)
                started.append(cname)
            for name, s in self.services.items():
                _ready(engine, f"{ses.tag}-{name}", name, s)
            if self.gateway:
                g = self.gateway
                _engine(engine, "network", "connect", "--alias", "gateway", ses.network, g["container"])
                joined = True
                given = _meter(g, "open", ses.tag).get("env") or {}
                opened = True
                if not isinstance(given, dict):
                    raise JudgeError("the meter's open printed no env mapping")
                for k, v in given.items():
                    _check_name(k, "the meter's env")
                    v = str(v)
                    if len(v) < MIN_SECRET or "\n" in v:
                        raise JudgeError(f"the meter's env: {k}'s value is too short to scan output for, or spans lines")
                    ses.secrets[k] = v
                env.update(ses.secrets)
                env["MORPHOGEN_GATEWAY"] = f"http://gateway:{g['port']}"
            if env:
                ses.env_file = _env_file(ses.tmp / "run.env", env)
            yield ses
        finally:
            failing = sys.exc_info()[0] is not None
            try:
                if opened:
                    got = _meter(self.gateway, "close", ses.tag)
                    bad = [k for k, v in got.items() if not isinstance(v, (int, float)) or isinstance(v, bool)]
                    if bad and not failing:
                        raise JudgeError(f"the meter's close printed values that are not numbers: {', '.join(bad)}")
                    ses.metered = {k: float(v) for k, v in got.items() if k not in bad}
            except JudgeError:
                if not failing:
                    raise
            finally:
                for c in started:
                    subprocess.run([engine, "rm", "-f", "-t", "0", c], capture_output=True)
                if joined:
                    subprocess.run([engine, "network", "disconnect", "-f", ses.network, self.gateway["container"]],
                                   capture_output=True)
                if ses.network:
                    subprocess.run([engine, "network", "rm", "-f", ses.network], capture_output=True)
                shutil.rmtree(ses.tmp, ignore_errors=True)


@dataclass
class Session:
    tag: str
    tmp: Path
    network: str | None = None
    env_file: Path | None = None
    secrets: dict[str, str] = field(default_factory=dict)        # what the meter gave this run
    metered: dict[str, float] = field(default_factory=dict)      # what the meter counted, after the run


def _meter(g: dict, op: str, run_id: str) -> dict:
    """Run the operator's meter outside the candidate (its own process, the operator's environment, in an empty
    directory) and read the one JSON object it prints."""
    with tempfile.TemporaryDirectory(prefix="morphogen-meter-") as d:
        try:
            p = subprocess.run(f"{g['meter']} {op} {run_id}", shell=True, cwd=d, capture_output=True, text=True,
                               timeout=g["meter_timeout"])
        except subprocess.TimeoutExpired:
            raise JudgeError(f"the meter's {op} took longer than {g['meter_timeout']}s") from None
    if p.returncode != 0:
        raise JudgeError(f"the meter's {op} failed (exit {p.returncode}): {p.stderr.strip()[-300:]}")
    try:
        out = json.loads(p.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise JudgeError(f"the meter's {op} printed no JSON object") from None
    if not isinstance(out, dict):
        raise JudgeError(f"the meter's {op} printed no JSON object")
    return out


def _engine(engine: str, *args: str) -> str:
    p = subprocess.run([engine, *args], capture_output=True, text=True)
    if p.returncode != 0:
        raise JudgeError(f"{engine} {args[0]} {args[1] if len(args) > 1 else ''} failed: {p.stderr.strip()[-300:]}")
    return p.stdout.strip()


def _env_file(path: Path, values: dict[str, str]) -> Path:
    path.touch(mode=0o600)
    path.write_text("".join(f"{k}={v}\n" for k, v in values.items()))
    return path


def _ready(engine: str, cname: str, name: str, s: dict) -> None:
    if not s.get("ready"):
        return
    deadline = time.monotonic() + s["ready_timeout"]
    while True:
        p = subprocess.run([engine, "exec", cname, "sh", "-c", s["ready"]], capture_output=True, text=True)
        if p.returncode == 0:
            return
        if time.monotonic() > deadline:
            raise JudgeError(f"service {name} was not ready within {s['ready_timeout']}s ({s['ready']})")
        time.sleep(0.5)


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines; blank lines and # comments skipped; `export ` and one pair of surrounding quotes allowed."""
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        k, sep, v = line.partition("=")
        if not sep:
            continue
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        out[k] = v
    return out


def _tracked(repo: Path, p: Path) -> bool:
    try:
        rel = p.relative_to(repo.resolve())
    except ValueError:
        return False
    r = subprocess.run(["git", "ls-files", "--error-unmatch", str(rel)], cwd=repo, capture_output=True)
    return r.returncode == 0


def _check_name(name: str, what: str) -> None:
    if not NAME.match(name):
        raise JudgeError(f"{what}: {name!r} is not an environment variable name")
    if name in RESERVED or name.startswith(RESERVED_PREFIXES):
        raise JudgeError(f"{what}: {name} is set by the judge or changes how the run starts; it cannot be served")


def _image_id(engine: str, image: str) -> str:
    p = subprocess.run([engine, "image", "inspect", "--format", "{{.Id}}", image], capture_output=True, text=True)
    if p.returncode != 0:
        _engine(engine, "pull", "-q", image)
        p = subprocess.run([engine, "image", "inspect", "--format", "{{.Id}}", image], capture_output=True, text=True)
    if p.returncode != 0 or not p.stdout.strip():
        raise JudgeError(f"the service image {image} cannot be found or pulled")
    return p.stdout.strip().splitlines()[0]


def _digest(values: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def prepare(cfg: dict, repo: Path) -> None:
    """Resolve the operator's `env` and `services` (cfg["local"]) into cfg["served"], or set it to None."""
    from .runner import sandbox_mode
    local = cfg.get("local") or {}
    env_spec, svc_spec, gw_spec = local.get("env"), local.get("services") or {}, local.get("gateway")
    cfg["served"] = None
    if not env_spec and not svc_spec and not gw_spec:
        return
    try:
        env = Env(**env_spec) if env_spec else None
        services = {n: Service(**(s or {})) for n, s in svc_spec.items()}
        gateway = Gateway(**gw_spec) if gw_spec else None
    except (ValidationError, TypeError) as e:
        raise JudgeError(f"morphogen.local.yaml's env or services: {e}") from None
    served, values = Served(), {}
    repo = Path(repo).resolve()
    if env:
        p = Path(env.file).expanduser()
        p = (p if p.is_absolute() else repo / p).resolve()
        if not p.is_file():
            raise JudgeError(f"env file {env.file!r} is not a file")
        if _tracked(repo, p):
            raise JudgeError(f"env file {env.file!r} is tracked by git: a commit could change its values; keep it "
                             "outside the repository, or untracked")
        values = read_env_file(p)
        served.file = p
    named = list(env.pass_ if env else []) + [n for s in services.values() for n in s.env]
    for n in named:
        _check_name(n, "env")
        if n not in values:
            raise JudgeError(f"env: {n} is not in the env file" if env else f"env: {n} named, but no env file")
        if "\n" in values[n]:
            raise JudgeError(f"env: {n}'s value spans lines")
    public = set(env.public if env else [])
    for n in named:
        if n not in public:
            if len(values[n]) < MIN_SECRET:
                raise JudgeError(f"env: {n}'s value is too short to scan output for; if it is not secret, list it "
                                 "under `public`")
            served.secrets[n] = values[n]
    served.passed = {n: values[n] for n in (env.pass_ if env else [])}
    used = {n: values[n] for n in named}
    served.digest = _digest(used) if used else None
    mode = sandbox_mode(cfg)
    if (services or gateway) and mode not in ("podman", "docker"):
        raise JudgeError("services and a gateway need a container runner (sandbox: podman or docker): without one "
                         "a run reaches whatever the machine reaches, around the gateway too, and a service's state "
                         "outlives the run")
    if gateway:
        if "gateway" in services:
            raise JudgeError("a service may not be called gateway: the run reaches the operator's gateway by that name")
        p = subprocess.run([mode, "container", "inspect", "--format", "{{.Image}} {{.State.Running}}", gateway.container],
                           capture_output=True, text=True)
        image, _, running = p.stdout.strip().partition(" ")
        if p.returncode != 0 or running != "true":
            raise JudgeError(f"the gateway container {gateway.container} is not running")
        served.gateway = gateway.model_dump()
        served.gateway["image_id"] = image
    if services:
        for n, s in services.items():
            if not SERVICE.match(n):
                raise JudgeError(f"service name {n!r}: lower-case letters, digits and dashes")
            served.services[n] = {"image": s.image, "id": _image_id(mode, s.image),
                                  "env": {k: values[k] for k in s.env}, "command": s.command,
                                  "ready": s.ready, "ready_timeout": s.ready_timeout}
    served.record = {
        **({"env": {"pass": sorted(served.passed), "public": sorted(public & set(named)),
                    "digest": served.digest}} if named else {}),
        **({"services": {n: {"image": s["image"], "id": s["id"], "env": sorted(s["env"])}
                         for n, s in served.services.items()}} if served.services else {}),
        **({"gateway": {"container": served.gateway["container"], "image_id": served.gateway["image_id"],
                        "port": served.gateway["port"],
                        "meter": hashlib.sha256(served.gateway["meter"].encode()).hexdigest()}} if served.gateway else {}),
    }
    cfg["served"] = served


def check(cfg: dict) -> None:
    """After the runs: the env file must hold the values it held before them."""
    served = cfg.get("served")
    if not served or not served.file:
        return
    try:
        values = read_env_file(served.file)
    except OSError:
        values = {}
    names = sorted(set(served.passed) | {k for s in served.services.values() for k in s["env"]})
    if _digest({n: values.get(n) for n in names}) != served.digest:
        raise JudgeError(f"the env file ({served.file}) changed during the runs: no verdict rests on them")


def record(cfg: dict) -> dict:
    """What a verdict records of the served values and services: names, a digest and image ids, never a value."""
    served = cfg.get("served")
    return {"served": served.record} if served and served.record else {}
