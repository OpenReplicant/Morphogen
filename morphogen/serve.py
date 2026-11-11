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
    record: dict = field(default_factory=dict)

    def leaks(self, *texts: str) -> list[str]:
        """The names whose value, in a form the scan knows, appears in any of `texts`."""
        out = []
        for name, v in self.secrets.items():
            b = v.encode()
            forms = {v, v[::-1], b.hex(), b.hex().upper(), urllib.parse.quote(v, safe=""),
                     base64.b64encode(b).decode().rstrip("="), base64.urlsafe_b64encode(b).decode().rstrip("=")}
            if any(f in t for t in texts if t for f in forms):
                out.append(name)
        return sorted(out)

    @contextmanager
    def session(self, engine: str, memory: str = "1g", cpus: str = "1"):
        """For one run in a container: an env file with the passed values (mode 600, never on a command line)
        and, when there are services, a network of the run's own with fresh services on it. Yields
        (network or None, env file or None); removes everything afterwards."""
        tmp = Path(tempfile.mkdtemp(prefix="morphogen-served-"))
        tag = "morphogen-" + secrets.token_hex(6)
        started, network = [], None
        try:
            env_file = None
            if self.passed:
                env_file = _env_file(tmp / "run.env", self.passed)
            if self.services:
                network = tag
                _engine(engine, "network", "create", "--internal", network)
                for name, s in self.services.items():
                    cname = f"{tag}-{name}"
                    args = ["run", "-d", "--rm", "--name", cname, "--network", network, "--network-alias", name,
                            "--memory", memory, "--cpus", cpus]
                    if s["env"]:
                        args += ["--env-file", str(_env_file(tmp / f"{name}.env", s["env"]))]
                    cmd = s["command"]
                    args += [s["id"], *(["sh", "-c", cmd] if isinstance(cmd, str) else cmd or [])]
                    _engine(engine, *args)
                    started.append(cname)
                for name, s in self.services.items():
                    _ready(engine, f"{tag}-{name}", name, s)
            yield network, env_file
        finally:
            for c in started:
                subprocess.run([engine, "rm", "-f", "-t", "0", c], capture_output=True)
            if network:
                subprocess.run([engine, "network", "rm", "-f", network], capture_output=True)
            shutil.rmtree(tmp, ignore_errors=True)


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
    env_spec, svc_spec = local.get("env"), local.get("services") or {}
    cfg["served"] = None
    if not env_spec and not svc_spec:
        return
    try:
        env = Env(**env_spec) if env_spec else None
        services = {n: Service(**(s or {})) for n, s in svc_spec.items()}
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
    if services:
        mode = sandbox_mode(cfg)
        if mode not in ("podman", "docker"):
            raise JudgeError("services need a container runner (sandbox: podman or docker): without one a run "
                             "reaches whatever the machine reaches, and a service's state outlives the run")
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
