"""Setting a project up, reporting what is true about it, and the journal."""

from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

import yaml

from .backend_files import FilesEvidenceLog, FilesListStore
from .config import data_dir, evidence_path, load_config, plugin_root
from .runner import docker_available

SAMPLES = plugin_root() / "samples"


def stores(root: Path, cfg: dict):
    backend = (cfg.get("backends") or {}).get("default", "files")
    if backend != "files":
        raise RuntimeError(f"backend {backend!r} is not available in this version; use 'files'")
    d = data_dir(root, cfg)
    return FilesListStore(d / "lists"), FilesEvidenceLog(evidence_path(root, cfg))


def init_project(root: Path) -> dict:
    """Create morphogen.yaml, the data directory, seed lists and a catalog, if missing."""
    done = []
    cfg_file = root / "morphogen.yaml"
    if not cfg_file.exists():
        shutil.copy(SAMPLES / "morphogen.example.yaml", cfg_file)
        done.append("wrote morphogen.yaml")
    cfg = load_config(root)
    lists, _ = stores(root, cfg)
    if not any(lists.query(k) for k in ("systems", "slots", "types", "sources", "components")):
        for f in sorted((SAMPLES / "lists").glob("*.jsonl")):
            for line in f.read_text().splitlines():
                if line.strip():
                    lists.put(f.stem, json.loads(line))
        done.append("seeded the six lists with Morphogen's own map")
    if not (root / "catalogs.yaml").exists():
        shutil.copy(SAMPLES / "catalogs.yaml", root / "catalogs.yaml")
        done.append("wrote catalogs.yaml")
    gi = root / ".gitignore"
    line = f"{cfg.get('data_dir', '.morphogen')}/traces.jsonl"
    existing = gi.read_text() if gi.exists() else ""
    if line not in existing.splitlines():
        gi.write_text(existing + ("" if existing.endswith("\n") or not existing else "\n") + line + "\n")
        done.append("ignored traces in .gitignore")
    return {"project": str(root), "done": done or ["already set up"]}


def install_sample(root: Path, name: str, dest: str | None) -> dict:
    src = SAMPLES / "targets" / name
    if not src.is_dir():
        available = sorted(p.name for p in (SAMPLES / "targets").iterdir() if p.is_dir())
        return {"error": f"no sample {name!r}; available: {', '.join(available)}"}
    dest = dest or f"targets/{name}"
    dst = root / dest
    if dst.exists():
        return {"error": f"{dest} already exists"}
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__"))
    cfg_file = root / "morphogen.yaml"
    if cfg_file.exists():
        cfg = yaml.safe_load(cfg_file.read_text()) or {}
        targets = cfg.get("targets") or []
        if dest not in targets:
            targets.append(dest)
            cfg["targets"] = targets
            cfg_file.write_text(yaml.safe_dump(cfg, sort_keys=False))
    return {"installed": dest, "next": f"commit it on the trunk, then measure it with measure(target='{dest}')"}


def doctor(root: Path) -> dict:
    cfg = load_config(root)
    report: dict = {"project": str(root), "plugin_root": str(plugin_root()),
                    "config": "found" if cfg["_found"] else "missing: run init_project"}
    try:
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=root, capture_output=True, text=True)
        report["git"] = "ok" if top.returncode == 0 else "not a git repository"
        trunk = cfg.get("trunk", "main")
        has = subprocess.run(["git", "rev-parse", "--verify", trunk], cwd=root, capture_output=True)
        report["trunk"] = f"{trunk}: {'exists' if has.returncode == 0 else 'missing'}"
    except OSError:
        report["git"] = "git not installed"
    try:
        lists, evidence = stores(root, cfg)
        ok, bad = evidence.verify()
        report["backend"] = (cfg.get("backends") or {}).get("default", "files")
        report["capabilities"] = {"lists": lists.capabilities, "evidence": evidence.capabilities}
        report["evidence"] = {"records": len(evidence.dump()), "path": str(evidence.path),
                              "chain": "intact" if ok else f"broken at record {bad}"}
    except Exception as e:  # report, do not crash
        report["backend"] = f"error: {e}"
    server_dir = Path(__file__).resolve().parent
    inside = root in server_dir.parents
    budget = (cfg.get("budget") or {}).get("trials_per_day", 0)
    report["guarantees"] = {
        "judge_outside_project": not inside,
        "timing": "measured outside the process under test",
        "inputs": "fresh random seeds per judge run; nothing stored to read in advance",
        "sandbox": "docker" if docker_available() else "none: trials run directly on this machine",
        "trials_per_day": budget or "no limit",
        "enforced_append_only": False,
        "note": "On the files backend the evidence log is tamper-evident (hash chain), not tamper-proof. "
                "An agent with shell access can still reach files you can; run in a container for "
                "the strong version.",
    }
    return report


def journal_append(root: Path, cfg: dict, entry: dict) -> dict:
    f = data_dir(root, cfg) / "journal.md"
    if not f.exists():
        f.write_text("# Journal\n\nAppend-only. One entry per change.\n")
    date = time.strftime("%Y-%m-%d", time.gmtime())
    lines = [f"\n## {date}: {entry.get('title', 'untitled')}\n"]
    for key in ("gap", "options", "choice", "why", "rung", "gate", "commit"):
        if entry.get(key):
            lines.append(f"- **{key.capitalize()}:** {entry[key]}")
    with f.open("a") as fh:
        fh.write("\n".join(lines) + "\n")
    return {"journal": str(f.relative_to(root)), "title": entry.get("title")}


def catalog_search(root: Path, cfg: dict, query: str, limit: int = 20) -> list[dict]:
    words = [w for w in query.lower().split() if w]
    found: list[tuple[int, dict]] = []

    def walk(node, where):
        if isinstance(node, dict):
            if "name" in node or "id" in node:
                text = json.dumps(node).lower()
                score = sum(text.count(w) for w in words)
                if score:
                    found.append((score, {"from": where, **node}))
            for v in node.values():
                walk(v, where)
        elif isinstance(node, list):
            for v in node:
                walk(v, where)

    cat = root / "catalogs.yaml"
    if cat.exists():
        walk(yaml.safe_load(cat.read_text()), "catalogs.yaml")
    lists, _ = stores(root, cfg)
    for kind in ("sources", "components", "types"):
        walk(lists.query(kind), f"lists/{kind}")
    found.sort(key=lambda p: -p[0])
    return [item for _, item in found[:limit]]
