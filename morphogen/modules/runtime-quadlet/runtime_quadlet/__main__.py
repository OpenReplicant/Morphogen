"""The runtime slot's Podman Quadlet provider (T27, R5-O9 as amended by R5-42 (c)): run each managed system as
systemd units Podman generates, from its compose file as committed in intent, but only a file a person approved
(T26). Which file may run, and the loop, are morphogen.runtime's, shared by every runtime; this provider is its
engine.

  python3 -m runtime_quadlet --intent DIR --system NAME [--project NAME]
  python3 -m runtime_quadlet --intent DIR --all        every system at HEAD, as project kk-<system>

An approved file (on the allow list every runtime applies) becomes one Quadlet application named after the project:
a `<project>.network` the system's services share, and per service a `<project>-<service>.container` (ContainerName
the same, NetworkAlias the service's name, so `http://backend:9898` still reaches the backend). Each compose key on
the allow list has its Quadlet key; values are written as Quadlet reads each key (quoted
where it splits words as systemd does, as they are elsewhere; `%` doubled everywhere; a line break is refused, and `$`
never reaches here). The units are handed to Podman as one `.quadlets` file (`podman quadlet install
--replace --application <project>`, Podman 5.6 or later), then `systemctl restart` starts every service unit
(`--user` when not root). A service the new file no longer has is stopped and the application removed before the
install (an application is removed as a whole). Podman and systemctl get only PATH, HOME, XDG_RUNTIME_DIR and
DBUS_SESSION_BUS_ADDRESS. Runs where systemd and Podman are, on the machine itself: the remote client has no quadlet
commands, so it does not run from inside Morphogen's container image (R5-39), where runtime-compose does.
Env: DATABASE_URL (its own login, or one that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_runtime_quadlet),
KK_INTENT_DIR (when --intent is not given).
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from morphogen import runtime

MODULE = "urn:kk:module:runtime-quadlet"
ENV = ("PATH", "HOME", "XDG_RUNTIME_DIR", "DBUS_SESSION_BUS_ADDRESS")
RESTART = {"always": "always", "unless-stopped": "always", "on-failure": "on-failure", "no": "no"}
HEALTH = {"interval": "HealthInterval", "timeout": "HealthTimeout", "retries": "HealthRetries",
          "start_period": "HealthStartPeriod"}


def raw(value) -> str:
    """A value Quadlet takes as it is (WorkingDir, User, HealthCmd, Entrypoint, ...: quotes would stay in it), with
    `%` doubled so no systemd specifier expands. A line break or a trailing backslash (which joins the next line) is
    refused."""
    s = "true" if value is True else "false" if value is False else str(value)
    if "\n" in s or "\r" in s or s.endswith("\\") or s != s.strip():
        raise ValueError(f"a unit setting cannot hold a line break, a trailing backslash or surrounding spaces: {s[:40]!r}")
    return s.replace("%", "%%")


def quote(value) -> str:
    """One word of a setting Quadlet splits as systemd does (Environment, Label, Exec): double-quoted, backslashes and
    quotes escaped, `%` doubled."""
    s = "true" if value is True else "false" if value is False else str(value)
    if "\n" in s or "\r" in s:
        raise ValueError(f"a value with a line break cannot be a unit setting: {s[:40]!r}")
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%") + '"'


def words(value) -> list[str]:
    """A compose command (a list, or a string split as a shell would) as a list of words."""
    return [str(v) for v in value] if isinstance(value, list) else shlex.split(str(value))


def pairs(value) -> list[tuple[str, str]]:
    """Compose environment or labels (a mapping, or a list of NAME=value) as (name, value) pairs."""
    if isinstance(value, dict):
        return [(str(k), "true" if v is True else "false" if v is False else str(v)) for k, v in value.items()]
    return [tuple(str(x).split("=", 1)) for x in value or []]


def render(project: str, text: bytes) -> dict[str, str]:
    """The Quadlet files for an approved compose file: {file name: content}."""
    services = yaml.safe_load(text)["services"]
    units = {f"{project}.network": "[Network]\n"}
    for name, svc in services.items():
        unit, container, service = [], [f"Image={raw(svc['image'])}", f"ContainerName={project}-{name}",
                                         f"Network={project}.network", f"NetworkAlias={name}"], []
        for k, v in pairs(svc.get("environment")):
            container.append(f"Environment={quote(f'{k}={v}')}")
        if "command" in svc:
            container.append("Exec=" + " ".join(quote(w) for w in words(svc["command"])))
        if "entrypoint" in svc:
            container.append("Entrypoint=" + raw(json.dumps(words(svc["entrypoint"]))))
        for p in svc.get("ports") or []:
            container.append(f"PublishPort={p}")
        for k, v in pairs(svc.get("labels")):
            container.append(f"Label={quote(f'{k}={v}')}")
        if "working_dir" in svc:
            container.append(f"WorkingDir={raw(svc['working_dir'])}")
        if "user" in svc:
            container.append(f"User={raw(svc['user'])}")
        health = svc.get("healthcheck") or {}
        if health.get("disable"):
            container.append("HealthCmd=none")
        elif "test" in health:
            test = health["test"]
            if isinstance(test, list) and test[:1] == ["CMD"]:
                container.append("HealthCmd=" + raw(json.dumps([str(t) for t in test[1:]])))
            elif isinstance(test, list) and test[:1] == ["CMD-SHELL"]:
                container.append("HealthCmd=" + raw(" ".join(str(t) for t in test[1:])))
            elif isinstance(test, str):
                container.append("HealthCmd=" + raw(test))
            else:
                raise ValueError(f"service {name}: a healthcheck test must be a string, CMD or CMD-SHELL")
            for key, setting in HEALTH.items():
                if key in health:
                    container.append(f"{setting}={raw(health[key])}")
        deps = svc.get("depends_on") or []
        for dep in (list(deps) if isinstance(deps, (dict, list)) else []):
            if not isinstance(dep, str) or not runtime.NAME.fullmatch(dep) or dep not in services:
                raise ValueError(f"service {name}: depends_on names only other services of this file, not {dep!r}")
            unit += [f"Requires={project}-{dep}.service", f"After={project}-{dep}.service"]
        if "restart" in svc:
            if str(svc["restart"]) not in RESTART:
                raise ValueError(f"service {name}: restart must be one of {', '.join(RESTART)}")
            service.append(f"Restart={RESTART[str(svc['restart'])]}")
        if any("\n" in line or "\r" in line for line in unit + container + service):     # one setting, one line
            raise ValueError(f"service {name}: a value would start another line of the unit")
        units[f"{project}-{name}.container"] = "".join(
            f"[{head}]\n" + "".join(line + "\n" for line in body) + "\n"
            for head, body in (("Unit", unit), ("Container", container), ("Service", service),
                               ("Install", ["WantedBy=default.target"])) if body)
    return units


def bundle(units: dict[str, str]) -> str:
    """Several Quadlet files as one `.quadlets` file (`# FileName=` names each, `---` between them)."""
    return "---\n".join(f"# FileName={name}\n{body}" for name, body in units.items())


class Quadlet:
    def run(self, *args: str, timeout: float = 300) -> subprocess.CompletedProcess:
        env = {k: v for k, v in os.environ.items() if k in ENV}
        return subprocess.run(list(args), env=env, capture_output=True, text=True, timeout=timeout)

    def apply(self, project: str, text: bytes, before: bytes | None) -> subprocess.CompletedProcess:
        try:
            units = render(project, text)
        except Exception as e:                    # anything the file cannot become is this system's failure
            return subprocess.CompletedProcess([], 1, "", f"{type(e).__name__}: {e}")
        user = [] if os.geteuid() == 0 else ["--user"]
        names = set(yaml.safe_load(text)["services"])
        gone = sorted(set(yaml.safe_load(before)["services"]) - names) if before else []
        if gone:
            self.run("systemctl", *user, "stop", *(f"{project}-{n}.service" for n in gone))
            out = self.run("podman", "quadlet", "rm", "--force", "--recursive", "--ignore", project)
            if out.returncode:
                return out
        with tempfile.TemporaryDirectory(prefix="kk-quadlet-") as d:
            path = Path(d) / f"{project}.quadlets"
            Path(d).chmod(0o700)
            path.write_text(bundle(units))
            out = self.run("podman", "quadlet", "install", "--replace", "--application", project, str(path))
        if out.returncode:
            return out
        return self.run("systemctl", *user, "restart", *(f"{project}-{n}.service" for n in sorted(names)))


def main(argv=None) -> int:
    return runtime.main(Quadlet(), MODULE, "kkm_runtime_quadlet",
                        "Run managed systems as Podman Quadlet units from their committed, approved compose files.", argv)


if __name__ == "__main__":
    sys.exit(main())
