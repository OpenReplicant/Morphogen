"""The research site for any system (site/README.md): `morphogen site init` writes a starter config and content
folder into a research project, and `morphogen site build` builds the static site from it with the Astro sources in
Morphogen's `site/` folder. The build itself is `npm run build` there, given the config, the output folder and the
base path in MORPHOGEN_SITE_CONFIG, MORPHOGEN_SITE_OUT and MORPHOGEN_SITE_BASE; this module only sets them."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tomllib
from pathlib import Path

import yaml

SITE = Path(__file__).resolve().parent.parent / "site"
LABELS = {"prioritise": ["research:prioritise"], "reject": ["research:reject"], "dispute": ["research:question"],
          "question": ["research:question"], "propose-role": ["research:question"],
          "propose-option": ["research:question"]}


class SiteError(Exception):
    pass


def site_dir() -> Path:
    d = Path(os.environ.get("MORPHOGEN_SITE_SRC") or SITE)
    if not (d / "package.json").is_file():
        raise SiteError(f"the site's sources are not at {d}: run Morphogen from a clone or the Claude Code plugin "
                        "(the Python package alone does not carry site/), or set MORPHOGEN_SITE_SRC")
    return d


def build(config: str | Path, out: str | Path, base: str = "", install: bool = False) -> Path:
    """Build the site from `config` into `out`. Returns the output folder."""
    d = site_dir()
    config, out = Path(config).resolve(), Path(out).resolve()
    if not config.is_file():
        raise SiteError(f"no config file at {config} (morphogen site init writes one)")
    try:
        tomllib.loads(config.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as e:
        raise SiteError(f"{config} is not valid TOML: {e}") from e
    npm = shutil.which("npm")
    if npm is None:
        raise SiteError("the site needs Node 22.23.4 or later and npm")
    if not (d / "node_modules" / "astro").is_dir():
        if not install:
            raise SiteError(f"the site's packages are not installed: run `npm ci --ignore-scripts` in {d}, "
                            "or pass --install")
        subprocess.run([npm, "ci", "--ignore-scripts", "--no-fund", "--no-audit"], cwd=d, check=True)
    env = dict(os.environ, MORPHOGEN_SITE_CONFIG=str(config), MORPHOGEN_SITE_OUT=str(out),
               MORPHOGEN_SITE_BASE=base or "", ASTRO_TELEMETRY_DISABLED="1")
    r = subprocess.run([npm, "run", "--silent", "build", "--", "--force"], cwd=d, env=env)
    if r.returncode:
        raise SiteError(f"the build failed (exit {r.returncode}); its errors are above")
    return out


def _git_repo(root: Path) -> str | None:
    """owner/name of the GitHub remote `origin`, if there is one."""
    try:
        url = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"github\.com[:/]([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+?)(?:\.git)?/?$", url)
    return f"{m[1]}/{m[2]}" if m else None


def _system(root: Path) -> str | None:
    """system:default/NAME of the first System in the project's catalog-info.yaml."""
    f = root / "catalog-info.yaml"
    if not f.is_file():
        return None
    for doc in yaml.safe_load_all(f.read_text(encoding="utf-8")):
        if isinstance(doc, dict) and doc.get("kind") == "System" and (doc.get("metadata") or {}).get("name"):
            ns = doc["metadata"].get("namespace", "default")
            return f"system:{ns}/{doc['metadata']['name']}"
    return None


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


CONFIG = """\
# The research site for {title_plain} (Morphogen's site/README.md, "The config file"). Paths are relative to this
# file. Build it: morphogen site build --config {config_rel} --out _site [--base /research]

[site]
title = {title}
description = {description}
owner = {owner}
# Steering issues open here, and claim files are linked here on GitHub.
repo = {repo}
branch = "main"
# The System each claim's status is shown for: the `system` of its assessments.
system = {system}

[sources]
claims = ["claims"]                          # searched recursively for EvidenceClaim files
catalog = ["catalog-info.yaml", "catalog"]   # Backstage entity files, or folders of them; a missing one is skipped
research = "research"                        # queue.json, watch.yaml, seen.jsonl, index.json (each optional)
content = {content}                          # Markdown pages

# The labels on each steering link (the agent reads the `research-action:` line in the body first).
[labels]
{labels}

[theme]
# css = "site-theme.css"   # loaded after the default style; override its custom properties (--accent, --bg...)
# logo = "logo.svg"        # in the header, and the icon

[nav]
# Any of: claims, queue, predictions, roles, map, notes, search. Pages with `nav: N` in front matter come after.
pages = ["claims", "queue", "predictions", "roles", "map", "notes"]
"""

ABOUT = """\
---
title: About this site
description: What {title_plain} shows, and how to steer it.
kind: page
nav: 90
blocks: [statuses, steering, files]
---
This site lists claims from papers about options for the parts of {owner_plain}'s system, whether each is
expected to carry over to it, and what our own trials found. It is rebuilt from the files in the repository.

Edit this page in `{content_rel}/about.md`. Every `.md` file in that folder becomes a page; give one
`kind: note` and a `date` to list it on the notes page, and `refs: [claim:NAME, resource:NAME]` to link it from
those pages.
"""


def init(root: str | Path, *, repo: str | None = None, system: str | None = None, title: str | None = None,
         owner: str | None = None, config: str = "site.toml", content: str = "site", force: bool = False) -> dict:
    """Write a starter config and content folder into the research project `root`. Returns what was written."""
    root = Path(root).resolve()
    repo = repo or _git_repo(root)
    system = system or _system(root)
    if not repo:
        raise SiteError("pass --repo OWNER/NAME (no GitHub remote named origin was found)")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise SiteError(f"--repo must be OWNER/NAME, not {repo}")
    if not system:
        raise SiteError("pass --system system:default/NAME (no System in catalog-info.yaml)")
    if not system.startswith("system:"):
        system = f"system:default/{system}"
    owner = owner or repo.split("/")[0]
    title = title or f"{repo.split('/')[1]} research"
    cfg, about = root / config, root / content / "about.md"
    for f in (cfg, about):
        if f.exists() and not force:
            raise SiteError(f"{f} exists; pass --force to replace it")
    labels = "\n".join(f"{k} = [{', '.join(_q(x) for x in v)}]" for k, v in LABELS.items())
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text(CONFIG.format(
        title_plain=title, title=_q(title), config_rel=config,
        description=_q(f"Claims from papers about options for {owner}'s system, with transfer predictions and outcomes."),
        owner=_q(owner), repo=_q(repo), system=_q(system), content=_q(content), labels=labels), encoding="utf-8")
    about.parent.mkdir(parents=True, exist_ok=True)
    about.write_text(ABOUT.format(title_plain=title, owner_plain=owner, content_rel=content), encoding="utf-8")
    return {"config": str(cfg), "content": str(about.parent), "repo": repo, "system": system,
            "workflow_template": str(Path(__file__).resolve().parent.parent / "skills" / "research-loop" / "research-site.yml"),
            "next": f"morphogen site build --config {cfg} --out _site"}
