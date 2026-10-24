"""Catalogs as open component sets (R5-30): loading them, searching them through an adapter per kind, and the
rules (toggles) each entry is checked against. No database; adapters may read the network or a git repository.

A catalog is `intent/catalogs/<name>.yaml`: {kind, label, ... the adapter's settings, rules: {overrides}}.
An entry is a dict:
  {catalog, id, label, version, licence, source, description, kind, slots, properties, published, pinned,
   sha256, path}
of which only catalog, id and label are always there. Kinds:

  components  `components:` a list of entries written in the file: any domain (software, parts, materials)
  pypi        `projects:` names to look up, or the query's terms; PyPI's JSON API (`index`, default
              https://pypi.org/pypi): name, version, summary, licence, home page, upload time of the release
  providers   Morphogen providers (directories with a provider.yaml) in `source: {git: URL, commit: SHA,
              path: DIR}` (fetched at that commit) or `source: {dir: PATH}` (relative to the repository, with
              an optional `sha256` per provider in `pins:`)

A query is {terms: [words], slot: <slot id>, kind: <entry kind>, min_age_days: N}: an entry matches when every term
occurs in its label, id, description or properties (case-insensitive), it fills the slot when one is asked for, its
kind is the one asked for, and, when it says when it was published, it is at least min_age_days old (a search
setting: intent/policies/catalogs.yaml `search:`, a catalog's own `search:`, then the query; 0 turns it off).
Rules (`rules:`, a catalog's own over them) are judged on every entry found:

  licences      {enforce, allow: [SPDX ids or names]}   the entry's licence is on the list
  pinned        {enforce}                               the entry names immutable content (a commit, a hash)

Each entry gets every rule's verdict; `offer(verdicts, rules)` is whether no enforced rule fails.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from morphogen.experiments import tree_hash

NAME = re.compile(r"[a-z0-9][a-z0-9_.-]*")
COMMIT = re.compile(r"[0-9a-f]{40}")


def load(intent: Path) -> dict[str, dict]:
    out = {}
    for f in sorted((Path(intent) / "catalogs").glob("*.yaml")):
        if not NAME.fullmatch(f.stem):
            continue
        c = yaml.safe_load(f.read_text()) or {}
        out[f.stem] = {**c, "name": f.stem, "file": f}
    return out


def rules(intent: Path, catalog: dict) -> dict:
    f = Path(intent) / "policies" / "catalogs.yaml"
    base = (yaml.safe_load(f.read_text()) or {}).get("rules", {}) if f.exists() else {}
    return {k: {**(base.get(k) or {}), **((catalog.get("rules") or {}).get(k) or {})} for k in set(base) | set(catalog.get("rules") or {})}


def settings(intent: Path, catalog: dict, query: dict) -> dict:
    """The search settings for a query: the policy's, the catalog's over them, the query's over both."""
    f = Path(intent) / "policies" / "catalogs.yaml"
    base = (yaml.safe_load(f.read_text()) or {}).get("search", {}) if f.exists() else {}
    return {**base, **(catalog.get("search") or {}), **{k: v for k, v in query.items() if k in ("min_age_days", "max_results")}}


def recent(e: dict, days, now: datetime | None = None) -> bool:
    """Whether the entry was published less than `days` ago (an entry that does not say is not recent)."""
    pub = e.get("published")
    if not days or not pub:
        return False
    when = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
    return (now or datetime.now(timezone.utc)) - when < timedelta(days=float(days))


def matches(e: dict, query: dict) -> bool:
    text = " ".join(str(x) for x in [e.get("id"), e.get("label"), e.get("description"),
                                       *(f"{k} {v}" for k, v in (e.get("properties") or {}).items())]).lower()
    if any(str(t).lower() not in text for t in query.get("terms") or []):
        return False
    if query.get("slot") and query["slot"] not in (e.get("slots") or []):
        return False
    if recent(e, query.get("min_age_days"), query.get("now")):
        return False
    return not query.get("kind") or e.get("kind") == query["kind"]


SPDX = [(re.compile(p, re.I), i) for p, i in [
    (r"\bLGPL-?v?3|Lesser General Public License v3", "LGPL-3.0"), (r"\bLGPL-?v?2\.1|Lesser General Public License v2", "LGPL-2.1"),
    (r"\bAGPL", "AGPL-3.0"), (r"(?<!L)GPL-?v?3|(?<!Lesser )General Public License v3", "GPL-3.0"),
    (r"(?<!L)GPL-?v?2|(?<!Lesser )General Public License v2", "GPL-2.0"), (r"\bApache", "Apache-2.0"), (r"\bMIT\b", "MIT"),
    (r"BSD-2|Simplified BSD|2-Clause", "BSD-2-Clause"), (r"BSD-3|New BSD|3-Clause|\bBSD\b", "BSD-3-Clause"), (r"\bISC\b", "ISC"),
    (r"\bMPL|Mozilla Public", "MPL-2.0"), (r"Python Software Foundation|\bPSF", "PSF-2.0"), (r"\bzlib\b", "Zlib")]]


def spdx(text) -> str | None:
    """The SPDX id a licence string names, for the common ways registries write them (else None)."""
    for pattern, ident in SPDX:
        if text and pattern.search(str(text)):
            return ident
    return None


def verdicts(e: dict, rules_: dict, now: datetime | None = None) -> dict:
    """{rule: {"ok": bool, "why": str, "enforced": bool}} for every rule configured."""
    now = now or datetime.now(timezone.utc)
    out = {}
    for name, r in sorted(rules_.items()):
        if name == "licences":
            allow = {str(x).lower() for x in r.get("allow") or []} | {(spdx(x) or "").lower() for x in r.get("allow") or []}
            lic = str(e.get("licence") or "")
            ok = bool(lic) and (lic.lower() in allow or (spdx(lic) or "?").lower() in allow)
            why = f"licence {e.get('licence')!r}" + ("" if ok else " is not on the list")
        elif name == "pinned":
            ok = bool(e.get("pinned"))
            why = "pinned content" if ok else "not pinned to immutable content"
        else:
            ok, why = False, f"unknown rule {name}"
        out[name] = {"ok": ok, "why": why, "enforced": bool(r.get("enforce"))}
    return out


def offer(v: dict) -> bool:
    return all(x["ok"] for x in v.values() if x["enforced"])


# ------------------------------------------------------------------ adapters
def components(cat: dict, query: dict) -> list[dict]:
    out = []
    for c in cat.get("components") or []:
        e = {**c, "catalog": cat["name"], "kind": c.get("kind", "component"), "adapter": "components"}
        e.setdefault("label", e.get("id"))
        e["pinned"] = bool(c.get("sha256"))        # a hash of the content; `pinned: true` alone states nothing checked
        if e.get("id") and matches(e, query):
            out.append(e)
    return out


def pypi(cat: dict, query: dict, fetch=None) -> list[dict]:
    index = str(cat.get("index", "https://pypi.org/pypi")).rstrip("/")
    get = fetch or (lambda url: json.load(urllib.request.urlopen(url, timeout=30)))
    names = list(cat.get("projects") or []) or [t for t in query.get("terms") or [] if NAME.fullmatch(str(t).lower())]
    out = []
    for name in names:
        try:
            url = f"{index}/{urllib.parse.quote(str(name))}/json"
            d = get(url)
        except Exception:
            continue                                     # not a project there
        i = d.get("info") or {}
        files = d.get("urls") or []
        e = {"catalog": cat["name"], "adapter": "pypi", "read_from": url, "kind": "python-package", "id": i.get("name") or name, "label": i.get("name") or name,
             "version": i.get("version"), "licence": i.get("license_expression") or i.get("license"),
             "description": i.get("summary"), "source": i.get("project_url") or f"https://pypi.org/project/{name}/",
             "published": min((f.get("upload_time_iso_8601") for f in files if f.get("upload_time_iso_8601")), default=None),
             "pinned": bool(files and all((f.get("digests") or {}).get("sha256") for f in files)),
             "properties": {"requires_python": i.get("requires_python")} if i.get("requires_python") else {}}
        q = {k: v for k, v in query.items() if k != "terms"} if not cat.get("projects") else query
        if matches(e, q):
            out.append(e)
    return out


def providers(cat: dict, query: dict, workdir: Path | None = None) -> list[dict]:
    """Provider entries; with `workdir`, their trees are fetched there (each entry's `path`)."""
    src = cat.get("source") or {}
    tmp = Path(tempfile.mkdtemp(prefix="kk-catalog-")) if workdir is None else workdir
    try:
        if src.get("git"):
            ref = str(src.get("commit") or "")
            pinned = bool(COMMIT.fullmatch(ref))
            subprocess.run(["git", "clone", "--quiet", "--no-checkout", str(src["git"]), str(tmp / "repo")], check=True,
                           capture_output=True, text=True, timeout=600)
            subprocess.run(["git", "-C", str(tmp / "repo"), "checkout", "--quiet", "--detach",
                            f"{ref}^{{commit}}" if pinned else (ref or "HEAD"), "--"], check=True,
                           capture_output=True, text=True, timeout=600)
            head = subprocess.run(["git", "-C", str(tmp / "repo"), "rev-parse", "HEAD"], check=True, capture_output=True,
                                  text=True).stdout.strip()
            if pinned and head != ref:
                raise ValueError(f"checked out {head}, not the pinned {ref}")
            root = (tmp / "repo" / str(src.get("path", "."))).resolve()
            if not root.is_relative_to((tmp / "repo").resolve()):
                raise ValueError(f"source path {src.get('path')!r} leaves the repository")
            where = f"{src['git']}@{head if pinned else ref or 'HEAD'}"
        elif src.get("dir"):
            from morphogen.experiments import ROOT
            root, pinned, where = (ROOT / src["dir"]).resolve(), False, f"file:{src['dir']}"
            if not root.is_relative_to(ROOT.resolve()):
                raise ValueError(f"source dir {src['dir']!r} leaves the repository")
        else:
            return []
        pins = cat.get("pins") or {}
        out = []
        for meta_f in sorted(root.glob("*/provider.yaml")):
            meta = yaml.safe_load(meta_f.read_text()) or {}
            d = meta_f.parent
            sha = tree_hash(d)
            stated = pins.get(str(meta.get("id", "")))
            e = {"catalog": cat["name"], "adapter": "providers", "kind": "provider", "id": str(meta.get("id", "")), "label": meta.get("name") or meta.get("id"),
                 "version": meta.get("version"), "licence": meta.get("license"), "slots": list(meta.get("slots") or []),
                 "description": meta.get("note") or meta.get("origin"), "source": f"{where}#{d.relative_to(root)}",
                 "sha256": sha, "pinned": pinned or (stated == sha), "path": str(d) if workdir is not None else None,
                 "read_from": f"{where}#{d.relative_to(root)}"}
            if stated and stated != sha:
                e["pinned"], e["mismatch"] = False, f"content {sha[:12]} is not the pinned {stated[:12]}"
            if e["id"].startswith("urn:kk:provider:") and matches(e, query):
                out.append(e)
        return out
    finally:
        if workdir is None:
            shutil.rmtree(tmp, ignore_errors=True)


ADAPTERS = {"components": components, "pypi": pypi, "providers": providers}


def search(cat: dict, query: dict, **kw) -> list[dict]:
    adapter = ADAPTERS.get(cat.get("kind"))
    if adapter is None:
        raise ValueError(f"catalog {cat.get('name')}: no adapter for kind {cat.get('kind')!r}")
    return adapter(cat, query, **kw)
