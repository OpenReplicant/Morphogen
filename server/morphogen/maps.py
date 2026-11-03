"""Several maps, and references between them.

A project's own lists are one map. `morphogen.yaml` can mount others, read-only:

    maps:
      homelab: {path: ../homelab, commit: 3f2a9c1}        # a git repository, read at a commit
      games:   {git: https://github.com/you/games-map, commit: 3f2a9c1}
      notes:   {path: ../notes/.morphogen/lists}            # a directory, read as it is now (unpinned)

`lists` names the lists directory inside a repository (default `.morphogen/lists`).
A pinned map is read from git objects at its commit, so later commits or edits
to its files change nothing here. An unpinned map is read live and reported as
such.

A reference to another map is a qualified id, `homelab:comp/gpu-box`. A bare id
means the map the entry lives in. Entries returned from a mounted map carry
`_map` (its name) and `_trust: stated` (another map's claim, not checked here),
and their references are qualified, so following them stays in the right map.

Mounted maps are read-only here: a map changes only in its own project,
through its own judge. Writing to one is refused.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

from .backend_files import FilesListStore, _matches
from .ports import KINDS, REF_FIELDS

SEP = ":"
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
# REF_FIELDS (ports.py): fields that hold references. A bare id resolves in the entry's own map.
ALL_REF_FIELDS = {f for fields in REF_FIELDS.values() for f in fields}
DEFAULT_LISTS = ".morphogen/lists"


class MapError(Exception):
    pass


def _git(cwd: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)


def _parse(text: str) -> dict[str, dict]:
    import json
    out = {}
    for line in text.splitlines():
        if line.strip():
            e = json.loads(line)
            if isinstance(e, dict) and e.get("id"):
                out[str(e["id"])] = e
    return out


class MountedMap:
    """A read-only map, loaded once when mounted."""

    def __init__(self, name: str, spec: dict, root: Path, cache: Path):
        self.name, self.spec = name, dict(spec)
        self.entries: dict[str, dict[str, dict]] = {k: {} for k in KINDS}
        self.commit = spec.get("commit")
        self.pinned = bool(self.commit)
        self.error: str | None = None
        try:
            self._load(root, cache)
        except MapError as e:
            self.error = str(e)

    def _load(self, root: Path, cache: Path) -> None:
        lists = self.spec.get("lists", DEFAULT_LISTS)
        if "git" in self.spec:
            if not self.commit:
                raise MapError("a git map needs a commit to pin it")
            repo = cache / self.name
            if not (repo / ".git").exists():
                repo.parent.mkdir(parents=True, exist_ok=True)
                r = subprocess.run(["git", "clone", "--quiet", str(self.spec["git"]), str(repo)],
                                   capture_output=True, text=True)
                if r.returncode != 0:
                    raise MapError(f"could not clone {self.spec['git']}: {r.stderr.strip()[-200:]}")
            if _git(repo, "cat-file", "-e", f"{self.commit}^{{commit}}").returncode != 0:
                _git(repo, "fetch", "--quiet", "origin")
            self._load_commit(repo, lists)
        elif "path" in self.spec:
            path = (root / self.spec["path"]).resolve()
            if self.commit:
                self._load_commit(path, lists)
            else:
                d = path if any((path / f"{k}.jsonl").exists() for k in KINDS) else path / lists
                if not d.is_dir():
                    raise MapError(f"no lists at {d}")
                for k in KINDS:
                    f = d / f"{k}.jsonl"
                    if f.exists():
                        self.entries[k] = _parse(f.read_text())
        else:
            raise MapError("a map needs a path or a git URL")

    def _load_commit(self, repo: Path, lists: str) -> None:
        full = _git(repo, "rev-parse", "--verify", "--quiet", f"{self.commit}^{{commit}}")
        if full.returncode != 0:
            raise MapError(f"commit {self.commit} not found in {repo}")
        self.commit = full.stdout.strip()
        for k in KINDS:
            r = _git(repo, "show", f"{self.commit}:{lists.strip('/')}/{k}.jsonl")
            if r.returncode == 0:
                self.entries[k] = _parse(r.stdout)

    def status(self) -> dict:
        return {"name": self.name, "source": self.spec.get("git") or self.spec.get("path"),
                "pinned": self.pinned, "commit": self.commit if self.pinned else None,
                "entries": sum(len(v) for v in self.entries.values()), "error": self.error}


class Atlas:
    """The project's own map plus mounted ones, behind the list-store interface.

    Reads resolve qualified ids; writes go to the own map only.
    """

    def __init__(self, own: FilesListStore, mounts: dict[str, MountedMap] | None = None, own_name: str = "local"):
        self.own, self.own_name = own, own_name
        self.mounts = mounts or {}
        self.capabilities = {**own.capabilities, "maps": sorted(self.mounts)}

    # --- ids
    def split(self, id: str, base: str | None = None) -> tuple[str, str]:
        """(map, local id). A bare id belongs to `base` (default: the own map)."""
        if SEP in id:
            prefix, rest = id.split(SEP, 1)
            return prefix, rest
        return (base or self.own_name), id

    def qualify(self, map_name: str, id: str) -> str:
        m, local = self.split(id, map_name)
        return local if m == self.own_name else f"{m}{SEP}{local}"

    def _store_get(self, map_name: str, kind: str, local: str) -> dict | None:
        if map_name == self.own_name:
            return self.own.get(kind, local)
        m = self.mounts.get(map_name)
        return m.entries.get(kind, {}).get(local) if m else None

    def _present(self, map_name: str, entry: dict, kind: str | None = None) -> dict:
        """An entry as seen from the own map: foreign ones annotated, references qualified."""
        if map_name == self.own_name:
            return entry
        out = {**entry, "id": f"{map_name}{SEP}{entry['id']}", "_map": map_name, "_trust": "stated"}
        for field in (REF_FIELDS.get(kind, ()) if kind else ALL_REF_FIELDS):
            v = entry.get(field)
            if isinstance(v, list):
                out[field] = [self.qualify(map_name, str(x)) for x in v]
            elif isinstance(v, str) and v:
                out[field] = self.qualify(map_name, v)
        return out

    # --- the list-store interface
    def get(self, kind: str, id: str) -> dict | None:
        m, local = self.split(id)
        e = self._store_get(m, kind, local)
        return self._present(m, e, kind) if e else None

    def put(self, kind: str, entry: dict) -> dict:
        if not isinstance(entry, dict) or not entry.get("id"):
            raise ValueError("an entry needs a non-empty 'id'")
        m, local = self.split(str(entry["id"]))
        if m != self.own_name and m not in self.mounts:
            raise ValueError(f"{SEP!r} separates a map name from an id, and no map named {m!r} is mounted")
        if m != self.own_name:
            raise PermissionError(f"map {m!r} is read-only here; change it in its own project, through its own judge")
        return self.own.put(kind, {k: v for k, v in entry.items() if k not in ("_map", "_trust")} | {"id": local})

    def query(self, kind: str, where: dict[str, Any] | None = None, map: str | None = None) -> list[dict]:
        """`map`: None or the own map's name (default), a mounted map's name, or '*' for all."""
        names = [self.own_name, *sorted(self.mounts)] if map == "*" else [map or self.own_name]
        out = []
        for name in names:
            if name == self.own_name:
                out += self.own.query(kind, where)
            elif name in self.mounts:
                out += [self._present(name, e, kind) for e in self.mounts[name].entries.get(kind, {}).values()
                        if _matches(e, where or {})]
            else:
                raise KeyError(f"no map named {name!r}; mounted: {', '.join(sorted(self.mounts)) or 'none'}")
        return out

    def _any(self, id: str) -> dict | None:
        """The entry with this (qualified) id in any list, presented as seen from here."""
        m, local = self.split(id)
        for kind in KINDS:
            e = self._store_get(m, kind, local)
            if e:
                return self._present(m, e, kind)
        return None

    def follow(self, kind: str, id: str, field: str, hops: int = 1) -> list[dict]:
        """Entries reachable from `id` along reference `field`, across maps. Each is returned once."""
        start = self.get(kind, id) or self._any(id)
        if start is None:
            return []
        seen, frontier, out = {start["id"]}, [start], []
        for _ in range(max(hops, 0)):
            nxt = []
            for e in frontier:
                refs = e.get(field) or []
                for r in refs if isinstance(refs, list) else [refs]:
                    if r in seen:
                        continue
                    target = self._any(str(r))
                    if target:
                        seen.add(r)
                        out.append(target)
                        nxt.append(target)
            frontier = nxt
        return out

    def dump(self) -> dict[str, list[dict]]:
        return self.own.dump()

    def load(self, data: dict[str, list[dict]]) -> None:
        self.own.load(data)

    # --- maps
    def dangling(self) -> list[dict]:
        """References, in the own map and in every mounted one, that do not resolve."""
        problems = []
        sources = [(self.own_name, {k: {e["id"]: e for e in self.own.query(k)} for k in KINDS})]
        sources += [(n, m.entries) for n, m in sorted(self.mounts.items())]
        for map_name, entries in sources:
            for kind, rows in entries.items():
                for e in rows.values():
                    for field in REF_FIELDS.get(kind, ()):
                        v = e.get(field)
                        for r in (v if isinstance(v, list) else [v] if v else []):
                            target_map, local = self.split(str(r), map_name)
                            if target_map != self.own_name and target_map not in self.mounts:
                                why = f"map {target_map!r} is not mounted"
                            elif not any(self._store_get(target_map, k, local) for k in KINDS):
                                why = "no such entry"
                            else:
                                continue
                            problems.append({"map": map_name, "kind": kind, "id": e["id"], "field": field,
                                             "ref": r, "why": why})
        return problems

    def status(self) -> dict:
        return {"own": self.own_name, "mounted": [m.status() for _, m in sorted(self.mounts.items())],
                "dangling": self.dangling()}


def mount(root: Path, cfg: dict, own: FilesListStore, cache: Path) -> Atlas:
    own_name = str(cfg.get("map_name", "local"))
    if not NAME.match(own_name):
        raise MapError(f"map_name {own_name!r}: use lowercase letters, digits and hyphens")
    mounts = {}
    for name, spec in (cfg.get("maps") or {}).items():
        if not NAME.match(str(name)) or name == own_name:
            raise MapError(f"map name {name!r}: use lowercase letters, digits and hyphens, not {own_name!r}")
        if not isinstance(spec, dict):
            raise MapError(f"map {name!r}: expected path or git, and optionally commit and lists")
        mounts[name] = MountedMap(name, spec, root, cache)
    return Atlas(own, mounts, own_name)
