"""The runtime slot's Compose provider (T27, R5-O9 as amended by R5-42 (c); first written as deploy/compose.py, R5-25):
run each managed system's compose file as committed in intent, and again whenever the commit changes it, but only
a file a person approved (T26). Which file may run, and the loop, are morphogen.runtime's, shared by every runtime;
this provider is its engine: `docker compose up -d --wait --remove-orphans`.

  python3 -m runtime_compose --intent DIR --system NAME [--project NAME]
  python3 -m runtime_compose --intent DIR --all        every system at HEAD, as project kk-<system>

The file is copied into a fresh private directory and compose runs there with only PATH, HOME and DOCKER_HOST, so no
`.env` file or variable of ours reaches it (an environment entry without a value, which would pass one on, is refused
by the allow list). Needs Docker (or Podman's Docker-compatible socket).
Env: DATABASE_URL (its own login, or one that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_runtime_compose),
KK_INTENT_DIR (when --intent is not given), DOCKER_HOST.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from morphogen import runtime

MODULE = "urn:kk:module:runtime-compose"


def compose(project: str, workdir: Path, *args: str, timeout: float = 300) -> subprocess.CompletedProcess:
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "DOCKER_HOST")}
    return subprocess.run(["docker", "compose", "-p", project, "--project-directory", str(workdir), "-f",
                           str(workdir / "compose.yaml"), *args], cwd=workdir, env=env, capture_output=True, text=True,
                          timeout=timeout)


class Compose:
    def apply(self, project: str, text: bytes, before: bytes | None) -> subprocess.CompletedProcess:
        """`up -d --wait --remove-orphans` on this content, from a fresh private directory."""
        with tempfile.TemporaryDirectory(prefix="kk-compose-") as d:
            workdir = Path(d)
            workdir.chmod(0o700)
            (workdir / "compose.yaml").write_bytes(text)
            return compose(project, workdir, "up", "-d", "--wait", "--remove-orphans")


def main(argv=None) -> int:
    return runtime.main(Compose(), MODULE, "kkm_runtime_compose",
                        "Run managed systems as their committed, approved compose files say.", argv)


if __name__ == "__main__":
    sys.exit(main())
