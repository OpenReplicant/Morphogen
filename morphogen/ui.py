"""A local, read-only web UI: the structure, the evidence and the targets.

    morphogen ui [--port 8765] [--host 127.0.0.1]

One page (ui.html, Alpine.js and Mermaid from a CDN at pinned versions) over a small JSON API on
the standard library's HTTP server. It binds to localhost, has no authentication and changes
nothing: measuring, judging and tuning stay with the CLI and the MCP server.
"""

from __future__ import annotations

import json
import subprocess
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import judge as judge_mod
from .documents import DocumentError, load_config
from .evidence import Evidence
from .render import mermaid
from .structure import Structure, StructureError

PAGE = Path(__file__).with_name("ui.html")


class Api:
    """What the page reads. Each method returns JSON-ready data."""

    def __init__(self, root: Path):
        self.root = judge_mod.repo_root(root)

    def _cfg(self) -> dict:
        return load_config(self.root)

    def _evidence(self) -> Evidence:
        return Evidence.for_project(self.root)

    def _structure_file(self, file: str | None) -> Path:
        f = (self.root / (file or self._cfg().get("structure", "cells.yaml"))).resolve()
        f.relative_to(self.root)  # only files inside the project
        return f

    def overview(self) -> dict:
        ev = self._evidence()
        ok, at = ev.verify()
        recs = ev.dump()
        kinds: dict[str, int] = {}
        for r in recs:
            kinds[r.get("kind", "note")] = kinds.get(r.get("kind", "note"), 0) + 1
        cfg = self._cfg()
        return {"root": str(self.root), "structure": cfg.get("structure", "cells.yaml"),
                "sandbox": cfg.get("sandbox"), "evidence": {"chain": "intact" if ok else f"broken at record {at}",
                                                            "records": len(recs), "kinds": kinds}}

    def structure(self, file: str | None = None) -> dict:
        f = self._structure_file(file)
        if not f.exists():
            return {"file": str(f.relative_to(self.root)), "missing": True}
        s = Structure.load(f)
        return {"file": str(f.relative_to(self.root)), "roots": s.roots(),
                "cells": {c: {**cell.model_dump(exclude_none=True), "children": s.children(c)}
                          for c, cell in sorted(s.cells.items())},
                "interfaces": {i: {**spec.model_dump(exclude_none=True), "providers": s.providers(i),
                                   "consumers": s.consumers(i)} for i, spec in sorted(s.interfaces.items())},
                "findings": [f.__dict__ for f in s.check()], "coverage": s.coverage(), "mermaid": mermaid(s)}

    def scope(self, cell: str, file: str | None = None) -> dict:
        s = Structure.load(self._structure_file(file))
        cells = sorted(s.scope(cell))
        return {"cell": cell, "scope": cells, "touched": s.touched(cells), "boundary": s.boundary(cells),
                "tests": s.tests_for(cells), "neighbours": s.neighbours(cell)}

    def evidence(self, limit: int = 100, kind: str | None = None, by: str | None = None,
                 contains: str | None = None) -> list[dict]:
        out = []
        for rec in self._evidence().query(contains=contains, by=by, limit=10_000):
            if kind and rec.get("kind", "note") != kind:
                continue
            out.append(rec)
            if len(out) >= limit:
                break
        return out

    def targets(self) -> list[dict]:
        files = subprocess.run(["git", "ls-files", "*target.yaml", "**/target.yaml"], cwd=self.root,
                               capture_output=True, text=True).stdout.split()
        recs = self._evidence().dump()
        out = []
        for f in sorted(set(files)):
            rel = Path(f).parent
            entry: dict = {"path": str(rel)}
            try:
                spec = judge_mod.load_spec(self.root, rel)
                metrics = (spec.get("measure") or {}).get("metrics") or {}
                entry.update({"name": spec.get("name") or rel.name, "description": spec.get("description"),
                              "primary": next((k for k, v in metrics.items() if v.get("primary")), None),
                              "metrics": metrics, "parameters": spec.get("parameters") or {},
                              "harness": spec.get("harness") or []})
            except judge_mod.JudgeError as e:
                entry["error"] = str(e)
            mine = [r for r in recs if (r.get("subject") or {}).get("path") == str(rel)]
            for kind in ("measurement", "verdict", "probe"):
                last = [r for r in mine if r.get("kind") == kind]
                entry[f"last_{kind}"] = last[-1] if last else None
            entry["verdicts"] = {v: sum(1 for r in mine if r.get("verdict") == v) for v in ("pass", "fail")}
            out.append(entry)
        return out


def make_handler(api: Api):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            pass

        def _send(self, status: int, body: bytes, ctype: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data, status: int = 200) -> None:
            self._send(status, json.dumps(data, default=str).encode(), "application/json")

        def do_GET(self):
            url = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(url.query).items()}
            try:
                if url.path in ("/", "/index.html"):
                    return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                if url.path == "/api/overview":
                    return self._json(api.overview())
                if url.path == "/api/structure":
                    return self._json(api.structure(q.get("file")))
                if url.path == "/api/scope":
                    return self._json(api.scope(q["cell"], q.get("file")))
                if url.path == "/api/evidence":
                    return self._json(api.evidence(int(q.get("limit", 100)), q.get("kind") or None,
                                                   q.get("by") or None, q.get("contains") or None))
                if url.path == "/api/targets":
                    return self._json(api.targets())
                return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
            except (StructureError, DocumentError, judge_mod.JudgeError, KeyError, ValueError) as e:
                return self._json({"error": str(e)}, HTTPStatus.BAD_REQUEST)

    return Handler


def serve(root: Path, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(Api(root)))
