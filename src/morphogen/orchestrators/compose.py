"""Docker Compose adapter: reconciles `intent/environments/<env>/` with `docker compose up`.

Every `compose.yml`, `compose.yaml` or `docker-compose.yml` below the
environment folder is one `-f` file, in path order, under the project
`morphogen-<env>`. Reconciling an unchanged folder is skipped. An empty folder
takes the project down only with `prune_empty=True`.

    uv run python -m morphogen.orchestrators.compose --environment sandbox [--once] [--dry-run]

Runs where the Docker socket is; agents never get this process or its socket
(decision 0008).
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from opentelemetry.trace import SpanKind

from morphogen import telemetry
from morphogen.orchestrators import Result

log = logging.getLogger(__name__)
SLOT = "orchestrator"
COMPOSE_NAMES = ("compose.yml", "compose.yaml", "docker-compose.yml", "docker-compose.yaml")

Runner = Callable[[list[str]], tuple[int, str]]


def run(cmd: list[str]) -> tuple[int, str]:
    p = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return p.returncode, (p.stdout + p.stderr).strip()


class ComposeAdapter:
    def __init__(self, intent_dir: str | Path, environment: str = "sandbox",
                 runner: Runner = run, prune_empty: bool = False, docker: str = "docker") -> None:
        self.intent_dir = Path(intent_dir).resolve()
        self.environment = environment
        self.folder = self.intent_dir / "environments" / environment
        self.project = f"morphogen-{environment}"
        self.runner = runner
        self.prune_empty = prune_empty
        self.docker = docker
        self.applied: str | None = None

    def files(self) -> list[Path]:
        if not self.folder.is_dir():
            return []
        return sorted(p for p in self.folder.rglob("*") if p.name in COMPOSE_NAMES and p.is_file())

    def revision(self) -> str:
        """Hash of the folder's compose files: changes exactly when there is something to apply."""
        h = hashlib.sha256()
        for p in self.files():
            h.update(str(p.relative_to(self.folder)).encode() + b"\0" + p.read_bytes() + b"\0")
        return h.hexdigest()[:16]

    def commands(self) -> list[list[str]]:
        base = [self.docker, "compose", "-p", self.project]
        files = self.files()
        if files:
            return [[*base, *(a for f in files for a in ("-f", str(f))), "up", "-d", "--remove-orphans"]]
        return [[*base, "down", "--remove-orphans"]] if self.prune_empty else []

    def _traceparent(self) -> str | None:
        """Trace context the promoter left in the last commit touching this folder."""
        code, out = self.runner(["git", "-C", str(self.intent_dir), "log", "-1",
                                 "--format=%(trailers:key=Traceparent,valueonly)", "--",
                                 str(self.folder)])
        return out.strip().splitlines()[0] if code == 0 and out.strip() else None

    def reconcile(self, force: bool = False) -> Result:
        rev = self.revision()
        if rev == self.applied and not force:
            return Result(self.environment, rev, skipped="unchanged")
        cmds = self.commands()
        if not cmds:
            self.applied = rev
            return Result(self.environment, rev, skipped="no compose files")
        carrier = {"traceparent": tp} if (tp := self._traceparent()) else {}
        result = Result(self.environment, rev, commands=cmds)
        with telemetry.extracted(carrier), \
                telemetry.span(f"reconcile {self.environment}", SLOT, SpanKind.CONSUMER,
                               **{"morphogen.environment": self.environment,
                                  "morphogen.intent.revision": rev}):
            for cmd in cmds:
                with telemetry.client_span(" ".join(cmd[1:2] + cmd[-3:]), SLOT, "docker"):
                    code, out = self.runner(cmd)
                result.output += out
                if code != 0:
                    result.ok = False
                    log.error("reconcile %s failed (%s): %s", self.environment, code, out)
                    return result  # leave `applied` unset so the next pass retries
        self.applied = rev
        return result


def watch(adapter: ComposeAdapter, interval_s: float, once: bool = False) -> int:
    while True:
        r = adapter.reconcile()
        if not r.skipped:
            log.info("reconciled %s at %s: %s", r.environment, r.revision, "ok" if r.ok else "failed")
        if once:
            return 0 if r.ok else 1
        time.sleep(interval_s)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="morphogen-compose", description=__doc__.splitlines()[0])
    ap.add_argument("--intent-dir", default=os.environ.get("MORPHOGEN_INTENT_DIR", "intent"))
    ap.add_argument("--environment", default="sandbox")
    ap.add_argument("--interval", type=float, default=10.0)
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--dry-run", action="store_true", help="print the commands instead of running them")
    ap.add_argument("--prune-empty", action="store_true")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    telemetry.setup(SLOT)

    runner: Runner = run
    if args.dry_run:
        def runner(cmd: list[str]) -> tuple[int, str]:
            if cmd[0] == "git":
                return run(cmd)
            print(" ".join(cmd))
            return 0, ""
    adapter = ComposeAdapter(args.intent_dir, args.environment, runner, args.prune_empty)
    return watch(adapter, args.interval, args.once)


if __name__ == "__main__":
    sys.exit(main())
