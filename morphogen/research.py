"""The research loop's deterministic half (docs/research-loop.md, phase 1): watch arXiv for what a map cares about,
fetch papers as text, check that every quote a model took occurs in its source, write the claims as EvidenceClaim
files (schemas/evidence-claim.v1.json), apply steering from GitHub issues, and rank what to test next.

    python -I -m morphogen.research watch   ROOT [--days N] [--max N]
    python -I -m morphogen.research triage  ROOT ID... --status read|skipped --reason TEXT
    python -I -m morphogen.research fetch   ROOT ID
    python -I -m morphogen.research catalog ROOT DRAFT [--by TEXT]
    python -I -m morphogen.research steer   ROOT [--repo OWNER/NAME | --issues FILE]
    python -I -m morphogen.research rank    ROOT
    python -I -m morphogen.research check   ROOT [--fetch]

ROOT is a research project: `catalog-info.yaml` (the map: its System, its roles as Components with `spec.type: role`,
its own conditions as Resources), `claims/` (one file per claim), and `research/` (what this module keeps:
`watch.yaml`, `seen.jsonl`, `steering.jsonl`, `drafts/`, `queue.json`, `index.json`). The judgement in between,
which papers matter and what they claim, is the model's, through the `research-loop` skill; nothing here calls a
model.

Papers are untrusted input. They are kept outside ROOT, in a cache directory of their own (`--cache`, default
`$MORPHOGEN_RESEARCH_CACHE` or `~/.cache/morphogen-research`), parsed with the standard library's HTML parser, and
never executed. Their text is not committed: arXiv's default licence does not allow it to be redistributed, so
`check --fetch` fetches it again to re-check the quotes.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

import yaml

from . import backstage

USER_AGENT = "morphogen-research/0.1 (+https://github.com/OpenReplicant/Morphogen)"
ARXIV_API = "https://export.arxiv.org/api/query"
ARXIV = "https://arxiv.org"
INTERVAL = 3.1          # arXiv's API terms: no more than one request every three seconds, one connection at a time
EXTRACTOR = "morphogen.research html_to_text v1"
SCHEMA = Path(__file__).resolve().parents[1] / "schemas/evidence-claim.v1.json"
NAME = re.compile(r"^[a-z0-9]+([-_.][a-z0-9]+)*$")
ARXIV_ID = re.compile(r"(?:arxiv:)?(\d{4}\.\d{4,5})(v\d+)?", re.I)
STATUSES = ("new", "read", "skipped", "cataloged", "rejected", "no-text")


class ResearchError(ValueError):
    pass


class Loader(yaml.SafeLoader):
    """YAML as JSON sees it: a date stays a string, as the claim schema's `format: date` expects."""


Loader.yaml_implicit_resolvers = {k: [(t, r) for t, r in v if t != "tag:yaml.org,2002:timestamp"]
                                  for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()}


def load_yaml(path: Path):
    return yaml.load(Path(path).read_text(), Loader)


def dump_yaml(obj) -> str:
    return yaml.safe_dump(obj, sort_keys=False, allow_unicode=True, width=110)


def today() -> str:
    return dt.date.today().isoformat()


# ------------------------------------------------------------------ text and quotes

_SAME = {"‘": "'", "’": "'", "‚": "'", "‛": "'", "′": "'", "“": '"', "”": '"',
         "„": '"', "″": '"', "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-",
         "―": "-", "−": "-", " ": " ", " ": " ", " ": " ", " ": " "}
_DROP = {"­", "​", "‌", "‍", "⁠", "﻿"}


def _norm_map(s: str) -> tuple[str, list[int]]:
    """`s` normalised for matching (NFKC; curly quotes, dashes and odd spaces made plain; soft hyphens and zero-width
    characters dropped; runs of whitespace made one space), with the index in `s` of every character kept."""
    out, where, space = [], [], False
    for i, ch in enumerate(s):
        for c in unicodedata.normalize("NFKC", ch):
            c = _SAME.get(c, c)
            if c in _DROP:
                continue
            if c.isspace():
                space = bool(out)
                continue
            if space:
                out.append(" ")
                where.append(i)
                space = False
            out.append(c)
            where.append(i)
    return "".join(out), where


def normalize(s: str) -> str:
    return _norm_map(s)[0]


_BLOCK = {"p", "div", "section", "article", "figure", "figcaption", "table", "tr", "li", "ul", "ol", "h1", "h2", "h3",
          "h4", "h5", "h6", "br", "blockquote", "dd", "dt", "header", "footer", "caption", "nav"}
_SKIP = {"script", "style", "noscript", "svg", "button", "head", "template"}
_HEAD = {"h1": "#", "h2": "##", "h3": "###", "h4": "####", "h5": "#####", "h6": "######"}


class _Extractor(HTMLParser):
    """arXiv's LaTeXML HTML as plain text: maths as its TeX (`alttext`), table cells separated by tabs, headings as
    Markdown headings, and the span of every element with an `id` (S4, S4.T1, S4.p2) as an anchor."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.size = 0
        self.stack: list[tuple[str, str | None, int]] = []   # tag, id, start
        self.anchors: list[tuple[int, int, str]] = []
        self.skip = 0          # inside a skipped element (script, the math tree after its alttext)
        self.error = False
        self.only_article = False   # set when the page has a LaTeXML article: arXiv's site chrome is left out
        self.article = 0

    def _emit(self, s: str) -> None:
        if s and (self.article or not self.only_article):
            self.parts.append(s)
            self.size += len(s)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("meta", "link", "img", "input", "hr", "br", "wbr", "col", "source"):   # void elements
            if tag == "br" and not self.skip:
                self._emit("\n")
            return
        if "ltx_ERROR" in (a.get("class") or ""):
            self.error = True
        if self.skip:
            self.skip += 1
            self.stack.append((tag, None, self.size))
            return
        cls = a.get("class") or ""
        if tag == "article" and "ltx_document" in cls:
            self.article += 1
        if tag in _SKIP or any(c in cls for c in ("ltx_bibliography", "ltx_TOC", "ltx_page_navbar")) \
                or a.get("aria-hidden") == "true":
            self.skip = 1
            self.stack.append((tag, None, self.size))
            return
        if tag in _BLOCK:
            self._emit("\n")
        if tag in _HEAD:
            self._emit(_HEAD[tag] + " ")
        if tag in ("td", "th"):
            self._emit("\t")
        self.stack.append((tag, a.get("id"), self.size))
        if tag == "math":
            self._emit(" " + (a.get("alttext") or "").strip() + " ")
            self.skip = 1

    def handle_endtag(self, tag):
        if not any(t == tag for t, _, _ in self.stack):
            return
        while self.stack:
            t, ident, start = self.stack.pop()
            if self.skip:
                self.skip -= 1
            if ident and self.size > start:
                self.anchors.append((start, self.size, ident))
            if t in _BLOCK:
                self._emit("\n")
            if t == "article" and self.article:
                self.article -= 1
            if t == tag:
                break

    def handle_startendtag(self, tag, attrs):
        if tag == "br" and not self.skip:
            self._emit("\n")

    def handle_data(self, data):
        if not self.skip:
            self._emit(data)


def html_to_text(html: str) -> tuple[str, list[tuple[int, int, str]], bool]:
    """The text of an arXiv HTML page, its anchors (start, end, element id), and whether LaTeXML marked an error."""
    p = _Extractor()
    p.only_article = 'class="ltx_document' in html
    p.feed(html)
    p.close()
    text = "".join(p.parts)
    # tidy without moving offsets: anchors refer to `text` as built
    return text, sorted(p.anchors), p.error


def find_quote(quote: str, text: str, anchors: list[tuple[int, int, str]] | None = None) -> tuple[bool, str | None]:
    """Whether `quote` occurs in `text`, both normalised (normalize), and the innermost anchor around its start."""
    q = normalize(quote)
    if not q:
        return False, None
    t, where = _norm_map(text)
    i = t.find(q)
    if i < 0:
        return False, None
    start, end = where[i], where[i + len(q) - 1]
    best = None
    for a, b, ident in anchors or []:
        if a <= start and end < b and (best is None or b - a < best[1] - best[0]):
            best = (a, b, ident)
    return True, best[2] if best else None


# ------------------------------------------------------------------ arXiv

class Http:
    """Polite GETs: a generic User-Agent naming the project, one request at a time, at least INTERVAL seconds apart."""

    def __init__(self, interval: float = INTERVAL, opener=None):
        self.interval, self.last = interval, 0.0
        self.opener = opener or urllib.request.urlopen

    def get(self, url: str, timeout: float = 60) -> tuple[int, bytes]:
        wait = self.last + self.interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with self.opener(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, b""
        finally:
            self.last = time.monotonic()


def build_query(topic: dict, since: str | None = None, until: str | None = None) -> str:
    """arXiv's search_query for one watch topic: any of its phrases in the title or abstract, within its categories,
    submitted in [since, until] (YYYY-MM-DD)."""
    phrases = topic.get("terms") or []
    if not phrases:
        raise ResearchError(f"topic {topic.get('name')!r} has no terms")
    def one(p: str) -> str:
        p = re.sub(r'["()]', " ", str(p)).strip()
        return f'ti:"{p}" OR abs:"{p}"' if " " in p else f"ti:{p} OR abs:{p}"
    q = "(" + " OR ".join(one(p) for p in phrases) + ")"
    cats = topic.get("categories") or []
    if cats:
        q += " AND (" + " OR ".join(f"cat:{c}" for c in cats) + ")"
    if since:
        a = since.replace("-", "") + "0000"
        b = (until or today()).replace("-", "") + "2359"
        q += f" AND submittedDate:[{a} TO {b}]"
    return q


_ATOM = {"a": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def parse_feed(xml: bytes | str) -> list[dict]:
    """The entries of an arXiv API Atom feed: id (no version), version, title, abstract, dates, authors' count,
    primary category. arXiv's metadata (titles and abstracts) is CC0."""
    root = ET.fromstring(xml)
    out = []
    for e in root.findall("a:entry", _ATOM):
        raw = (e.findtext("a:id", "", _ATOM) or "").rsplit("/abs/", 1)[-1]
        m = ARXIV_ID.fullmatch(raw)
        if not m:
            continue
        prim = e.find("arxiv:primary_category", _ATOM)
        out.append({
            "id": m.group(1), "version": m.group(2) or "v1",
            "title": " ".join((e.findtext("a:title", "", _ATOM) or "").split()),
            "abstract": " ".join((e.findtext("a:summary", "", _ATOM) or "").split()),
            "published": (e.findtext("a:published", "", _ATOM) or "")[:10],
            "updated": (e.findtext("a:updated", "", _ATOM) or "")[:10],
            "authors": len(e.findall("a:author", _ATOM)),
            "category": prim.get("term") if prim is not None else None,
        })
    return out


def arxiv_id(s: str) -> tuple[str, str | None]:
    m = ARXIV_ID.fullmatch(s.strip())
    if not m:
        raise ResearchError(f"{s!r} is not an arXiv id (2611.01234 or 2611.01234v2)")
    return m.group(1), m.group(2)


def cache_dir(arg: str | None = None) -> Path:
    return Path(arg or os.environ.get("MORPHOGEN_RESEARCH_CACHE") or Path.home() / ".cache/morphogen-research")


def fetch_text(pid: str, version: str, cache: Path, http: Http | None = None) -> dict:
    """A paper's text in the cache, fetched once: arXiv's HTML first; the PDF through Docling when there is no HTML
    (or LaTeXML marked an error) and Docling is installed. Returns the record in `meta.json`."""
    d = cache / "papers" / f"{pid}{version}"
    meta = d / "meta.json"
    if meta.exists():
        return json.loads(meta.read_text())
    d.mkdir(parents=True, exist_ok=True)
    http = http or Http()
    status, body = http.get(f"{ARXIV}/html/{pid}{version}")
    rec: dict = {"id": pid, "version": version, "fetched": today()}
    error = False
    if status == 200 and body:
        (d / "source.html").write_bytes(body)
        text, anchors, error = html_to_text(body.decode("utf-8", "replace"))
        rec.update(route="html", url=f"{ARXIV}/html/{pid}{version}", sha256=hashlib.sha256(body).hexdigest(),
                   extractor=EXTRACTOR, latexml_error=error)
        (d / "text.md").write_text(text)
        (d / "anchors.json").write_text(json.dumps(anchors))
    if status != 200 or not body or error:
        docling = shutil.which("docling")
        if docling:
            st, pdf = http.get(f"{ARXIV}/pdf/{pid}{version}")
            if st == 200 and pdf:
                (d / "source.pdf").write_bytes(pdf)
                out = d / "docling"
                subprocess.run([docling, "--to", "md", "--output", str(out), str(d / "source.pdf")], check=True,
                               cwd=d, capture_output=True, timeout=1800)
                md = next(out.glob("*.md"))
                (d / "text.md").write_text(md.read_text())
                (d / "anchors.json").write_text("[]")
                rec.update(route="pdf+docling", url=f"{ARXIV}/pdf/{pid}{version}",
                           sha256=hashlib.sha256(pdf).hexdigest(), extractor="docling")
        elif "route" not in rec:
            rec.update(route="none", note=f"no HTML (HTTP {status}) and Docling is not installed "
                                          "(`uv tool install docling==2.153.0` adds the PDF route)")
    meta.write_text(json.dumps(rec, indent=1))
    return rec


def paper_text(pid: str, version: str, cache: Path) -> tuple[str, list] | None:
    d = cache / "papers" / f"{pid}{version}"
    if not (d / "text.md").exists():
        return None
    return (d / "text.md").read_text(), [tuple(a) for a in json.loads((d / "anchors.json").read_text())]


# ------------------------------------------------------------------ the project's files

class Project:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.dir = self.root / "research"
        if not (self.root / "catalog-info.yaml").exists():
            raise ResearchError(f"{self.root}: no catalog-info.yaml (the map)")

    # the map
    def entities(self) -> list[dict]:
        ents, _ = backstage.read(["catalog-info.yaml"], backstage.fs_reader(self.root))
        return ents

    def refs(self) -> dict[str, dict]:
        return {backstage.parse_ref(e["metadata"]["name"], str(e["kind"]).lower(),
                                    (e["metadata"].get("namespace") or "default")): e for e in self.entities()}

    def roles(self) -> dict[str, dict]:
        return {r: e for r, e in self.refs().items()
                if str(e["kind"]).lower() == "component" and str((e.get("spec") or {}).get("type")) == "role"}

    def watch(self) -> dict:
        w = load_yaml(self.dir / "watch.yaml") or {}
        if not w.get("system"):
            raise ResearchError("research/watch.yaml: name the system (system: system:default/NAME)")
        return w

    # seen papers: one JSON object a line, sorted by id, so a session's diff shows what it saw
    def seen(self) -> dict[str, dict]:
        f = self.dir / "seen.jsonl"
        if not f.exists():
            return {}
        return {r["id"]: r for r in map(json.loads, filter(None, f.read_text().splitlines()))}

    def save_seen(self, seen: dict[str, dict]) -> None:
        self.dir.mkdir(exist_ok=True)
        (self.dir / "seen.jsonl").write_text("".join(json.dumps(seen[k], ensure_ascii=False, sort_keys=True) + "\n"
                                                     for k in sorted(seen)))

    def steering(self) -> list[dict]:
        f = self.dir / "steering.jsonl"
        return [json.loads(x) for x in f.read_text().splitlines() if x.strip()] if f.exists() else []

    def funding(self) -> dict:
        """research/funding.yaml (optional): {currency, rate_per_hour, funds: {claim-or-direction id: {pledged,
        received, source}}}. The source is a free-text note (provider and reference); no personal data."""
        f = self.dir / "funding.yaml"
        d = load_yaml(f) if f.exists() else None
        d = d or {}
        funds = d.get("funds") or {}
        if not isinstance(funds, dict):
            raise ResearchError("research/funding.yaml: funds must map an id to {pledged, received, source}")
        for k, v in funds.items():
            for n in ("pledged", "received"):
                x = (v or {}).get(n, 0)
                if isinstance(x, bool) or not isinstance(x, (int, float)) or x < 0:
                    raise ResearchError(f"research/funding.yaml: {k}.{n} must be a number, 0 or more")
        rate = d.get("rate_per_hour")
        if funds and (isinstance(rate, bool) or not isinstance(rate, (int, float)) or rate <= 0):
            raise ResearchError("research/funding.yaml: rate_per_hour (money per trial hour) must be above 0")
        return {"currency": d.get("currency", "USD"), "rate_per_hour": rate, "funds": funds}

    def claims(self) -> dict[str, tuple[Path, dict]]:
        out = {}
        for f in sorted((self.root / "claims").rglob("*.yaml")):
            doc = load_yaml(f)
            out[doc["metadata"]["name"]] = (f, doc)
        return out

    def found_path(self) -> Path:
        return self.root / "catalog" / "found.yaml"

    def found(self) -> list[dict]:
        f = self.found_path()
        return [d for d in yaml.load_all(f.read_text(), Loader) if d] if f.exists() else []


def validator():
    from jsonschema import Draft202012Validator   # mcp's dependency, pinned in uv.lock
    schema = json.loads(SCHEMA.read_text())
    return Draft202012Validator(schema, format_checker=Draft202012Validator.FORMAT_CHECKER)


def schema_errors(doc: dict, v=None) -> list[str]:
    v = v or validator()
    return [f"{'/'.join(map(str, e.absolute_path)) or '(root)'}: {e.message}"
            for e in sorted(v.iter_errors(doc), key=lambda x: list(map(str, x.absolute_path)))]


# ------------------------------------------------------------------ watch

def watch(p: Project, days: int = 30, max_results: int = 25, http: Http | None = None) -> list[dict]:
    """Query arXiv once per topic in watch.yaml, newest first, over the last `days` days; add what was not seen
    before to seen.jsonl as `new`. Papers rejected by steering stay rejected."""
    w, seen, http = p.watch(), p.seen(), http or Http()
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    fresh = []
    for topic in w.get("topics") or []:
        q = build_query(topic, since)
        url = ARXIV_API + "?" + urllib.parse.urlencode({"search_query": q, "sortBy": "submittedDate",
                                                         "sortOrder": "descending", "max_results": max_results})
        status, body = http.get(url)
        if status != 200:
            print(f"topic {topic['name']}: arXiv answered HTTP {status}; skipped", file=sys.stderr)
            continue
        for e in parse_feed(body):
            r = seen.get(e["id"])
            if r:
                if topic["name"] not in r["topics"]:
                    r["topics"] = sorted(set(r["topics"]) | {topic["name"]})
                if e["version"] != r["version"] and r["status"] == "new":
                    r["version"] = e["version"]
                continue
            r = {**e, "topics": [topic["name"]], "roles": sorted(set(topic.get("roles") or [])), "status": "new",
                 "seen": today()}
            seen[e["id"]] = r
            fresh.append(r)
        for r in seen.values():
            if topic["name"] in r["topics"]:
                r["roles"] = sorted(set(r.get("roles") or []) | set(topic.get("roles") or []))
    p.save_seen(seen)
    return fresh


def triage(p: Project, ids: list[str], status: str, reason: str) -> None:
    if status not in STATUSES:
        raise ResearchError(f"status {status!r}: one of {', '.join(STATUSES)}")
    seen = p.seen()
    for i in ids:
        pid, _ = arxiv_id(i)
        if pid not in seen:
            raise ResearchError(f"{pid} is not in research/seen.jsonl (run watch first)")
        seen[pid].update(status=status, reason=reason, triaged=today())
    p.save_seen(seen)


# ------------------------------------------------------------------ catalog

def slug(s: str, limit: int = 63) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")
    return s[:limit].rstrip("-") or "x"


def claim_key(doc: dict) -> tuple[str, str]:
    """Two claims are the same claim when they come from the same paper (any version) with the same quote."""
    src = doc["spec"]["source"]
    pid = src.get("id") or src.get("url") or src.get("title")
    m = ARXIV_ID.search(pid or "")
    return (m.group(1) if m else pid), normalize(src.get("quote") or "").lower()


def build_claim(c: dict, paper: dict, watch: dict, by: str, where: str | None, date: str | None = None) -> dict:
    """An EvidenceClaim from one drafted claim and the paper it came from; its quote already found in the text."""
    date = date or today()
    claim = dict(c["claim"])
    pred = c.get("prediction") or {}
    a: dict = {"system": watch["system"]}
    if watch.get("against"):
        a["against"] = list(watch["against"])
    if pred.get("p_transfer") is not None:
        a.update(status="predicted", prediction={"p_transfer": float(pred["p_transfer"]), "reason": pred["reason"],
                                                 "by": by, "date": date, "before_outcome": True})
    else:
        a.update(status="untested", reason=pred.get("reason") or c.get("reason") or "no prediction drafted")
    if c.get("trial"):
        a["trial"] = c["trial"]
    a["date"] = date
    return {
        "apiVersion": "morphogen.dev/v1alpha1", "kind": "EvidenceClaim",
        "metadata": {"name": c["name"], "description": claim.get("statement", "").strip().split("\n")[0]},
        "spec": {
            "about": backstage.parse_ref(c["option"]["name"], "component"),
            "role": backstage.parse_ref(c["role"], "component"),
            "source": {
                "kind": "preprint", "title": paper["title"], "id": f"arXiv:{paper['id']}",
                "url": f"{ARXIV}/abs/{paper['id']}{paper['version']}", "version": paper["version"],
                "location": c.get("location") or "not stated", "read": c.get("read") or "in full",
                "quote": c["quote"].strip(), **({"quote_location": f"arXiv HTML #{where}"} if where else {}),
                "quote_status": "checked",
                "quote_note": f"matched against the paper's text ({paper.get('route', 'html')}, sha256 "
                              f"{(paper.get('sha256') or '')[:12]}) by {EXTRACTOR}, after NFKC and with quotes, "
                              "dashes and whitespace made plain",
            },
            "claim": claim,
            "conditions": c.get("conditions") or {},
            "assessments": [a],
        },
    }


def _option_entity(name: str, description: str, fills: list[str], evidence: list[str], url: str | None,
                   owner: str) -> dict:
    m: dict = {"fills": sorted(fills) if len(fills) > 1 else fills[0]}
    if url:
        m["docs"] = {"url": url}
    m["evaluation"] = {"evidence": sorted(evidence)}
    return {"apiVersion": "backstage.io/v1alpha1", "kind": "Component",
            "metadata": {"name": name, "description": description},
            "spec": {"type": "method", "lifecycle": "candidate", "owner": owner, "morphogen": m}}


def write_found(p: Project, extra: dict[str, dict] | None = None) -> None:
    """catalog/found.yaml: the options the loop found, one Component each, its evidence list kept equal to the
    claims about it. Hand-written options live in other catalog files and are not touched."""
    old = {e["metadata"]["name"]: e for e in p.found()}
    for name, e in (extra or {}).items():
        if name not in old:
            old[name] = e
        elif old[name]["metadata"].get("description") in (None, "", name):   # a later claim described it
            old[name]["metadata"]["description"] = e["metadata"]["description"]
    claims = p.claims()
    out = []
    for name in sorted(old):
        e = old[name]
        ref = backstage.parse_ref(name, "component")
        mine = [(f, d) for f, d in claims.values() if backstage.parse_ref(d["spec"]["about"], "component") == ref]
        if not mine:
            continue
        m = e["spec"]["morphogen"]
        fills = m.get("fills") or []
        fills = set([fills] if isinstance(fills, str) else fills) | {d["spec"]["role"] for _, d in mine}
        out.append(_option_entity(name, e["metadata"].get("description", ""), sorted(fills),
                                  [f.relative_to(p.root).as_posix() for f, _ in mine],
                                  (m.get("docs") or {}).get("url"), e["spec"].get("owner", "group:default/research")))
    head = ("# The options the research loop found (morphogen.research catalog writes this file; edit the claims, "
            "not this).\n# Each lists its claim files in spec.morphogen.evaluation.evidence.\n")
    p.found_path().parent.mkdir(exist_ok=True)
    p.found_path().write_text(head + "---\n".join(dump_yaml(e) for e in out))


def catalog(p: Project, draft_path: Path, cache: Path, by: str, http: Http | None = None,
            date: str | None = None) -> dict:
    """Turn a drafted paper (research/drafts/ID.yaml, the model's extraction) into claim files. A claim is written
    only if its quote occurs in the paper's text, the file validates against the schema, its role is a role on the
    map, and it is not a claim already held (same paper, same quote). Returns what was written and refused."""
    try:
        draft = load_yaml(draft_path) or {}
    except yaml.YAMLError as e:
        raise ResearchError(f"{draft_path}: not valid YAML ({e})") from None
    pid, ver = arxiv_id(str(draft.get("paper", "")))
    seen = p.seen()
    meta = seen.get(pid) or {}
    ver = ver or meta.get("version") or "v1"
    rec = fetch_text(pid, ver, cache, http)
    txt = paper_text(pid, ver, cache)
    if txt is None:
        raise ResearchError(f"{pid}{ver}: no text to check quotes against ({rec.get('note', rec.get('route'))})")
    text, anchors = txt
    paper = {"id": pid, "version": ver, "title": draft.get("title") or meta.get("title") or pid, **rec}
    w, roles, v = p.watch(), p.roles(), validator()
    refs = p.refs()
    found_names = {e["metadata"]["name"] for e in p.found()}
    held = {claim_key(d): n for n, (_, d) in p.claims().items()}
    names = set(p.claims())
    written, refused, options = [], [], {}
    for c in draft.get("claims") or []:
        label = c.get("name") or "(unnamed)"
        try:
            name = c.get("name") or ""
            if not NAME.fullmatch(name) or len(name) > 63:
                name = slug(name or c.get("claim", {}).get("statement", "claim"), 60)
            c = {**c, "name": name, "read": c.get("read") or draft.get("read")}
            opt = c.get("option") or {}
            if not opt.get("name"):
                raise ResearchError("no option named (the method, as option: {name, description})")
            oname = slug(opt["name"])
            oref = backstage.parse_ref(oname, "component")
            if oref in refs and oname not in found_names:
                raise ResearchError(f"option {oname} is a hand-written entity ({refs[oref]['_file']}); name a new "
                                    "option, or list this claim there by hand")
            c["option"] = {**opt, "name": oname}
            desc = opt.get("description") or next((x["option"].get("description") for x in draft["claims"]
                                                   if slug((x.get("option") or {}).get("name") or "") == oname
                                                   and x["option"].get("description")), None)
            options.setdefault(oname, _option_entity(oname, desc or oname, [backstage.parse_ref(c["role"], "component")],
                                                     [], f"{ARXIV}/abs/{pid}{ver}",
                                                     w.get("owner") or "group:default/research"))
            if backstage.parse_ref(c.get("role") or "", "component") not in roles:
                raise ResearchError(f"role {c.get('role')!r} is not a role on the map ({', '.join(sorted(roles))})")
            ok, where = find_quote(c.get("quote") or "", text, anchors)
            if not ok:
                raise ResearchError("quote not found in the paper's text: " + (c.get("quote") or "")[:80])
            doc = build_claim(c, paper, w, by, where, date)
            errs = schema_errors(doc, v)
            if errs:
                raise ResearchError("schema: " + "; ".join(errs[:4]))
            k = claim_key(doc)
            if k in held:
                raise ResearchError(f"a duplicate of {held[k]} (same paper, same quote)")
            base, n = name, 2
            while name in names:
                name = f"{base[:60]}-{n}"
                n += 1
            doc["metadata"]["name"] = name
            f = p.root / "claims" / f"arxiv-{pid}" / f"{name}.yaml"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(dump_yaml(doc))
            held[k], names = name, names | {name}
            written.append(f.relative_to(p.root).as_posix())
        except (ResearchError, backstage.CatalogError, KeyError, TypeError) as e:
            refused.append({"claim": label, "why": str(e)})
    write_found(p, options)
    if pid in seen:
        seen[pid].update(status="cataloged" if written else seen[pid]["status"], cataloged=today(),
                         claims=sorted(set(seen[pid].get("claims") or []) |
                                       {Path(x).stem for x in written}))
        p.save_seen(seen)
    return {"paper": f"{pid}{ver}", "written": written, "refused": refused}


# ------------------------------------------------------------------ steering

LABELS = {"research:prioritise": "prioritise", "research:prioritize": "prioritise", "research:reject": "reject",
          "research:question": "question"}
# The `research-action:` line the claim site (site/src/lib/steer.mjs; PR #108 first) writes into every issue body: the primary signal,
# since GitHub drops a prefilled link's labels for anyone without triage access.
ACTIONS = {"prioritise", "reject", "dispute", "question", "propose-role", "propose-option"}
TOPICAL = {"question", "propose-role", "propose-option"}   # these become a watch topic waiting for terms
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}
_TARGET = re.compile(r"^\s*(claim|paper|role|option)\s*:\s*(\S+)", re.I | re.M)
_META = re.compile(r"^\s*(research-action|research-claim|claim-file|system|status|p_transfer)\s*:\s*(.*?)\s*$",
                   re.I | re.M)
_PREFIX = re.compile(r"^\s*\[(research:[a-z]+)\]\s*", re.I)


def parse_issue(issue: dict) -> dict | None:
    """One GitHub issue (the REST API's shape) as a steering event, or None when it is not one.

    The kind is, in order: the body's `research-action:` line (prioritise, reject, dispute, question, propose-role,
    propose-option; the claim site writes it), a `research:*` label, or a title starting `[research:...]`. The target
    is the body's `research-claim:` line, else a `claim:`, `paper:`, `role:` or `option:` line in the body or title;
    `claim-file:` is kept as given. Only the repository's owner, members and collaborators steer; anyone else's issue
    is recorded as not applied."""
    if "pull_request" in issue:
        return None
    body = issue.get("body") or ""
    meta = {k.lower(): v for k, v in _META.findall(body)}
    labels = [(x["name"] if isinstance(x, dict) else str(x)).lower() for x in issue.get("labels") or []]
    title = issue.get("title") or ""
    m = _PREFIX.match(title)
    action = (meta.get("research-action") or "").lower()
    kind = (action if action in ACTIONS else None) or next((LABELS[x] for x in labels if x in LABELS), None)
    if not kind and m and m.group(1).lower() in LABELS:
        kind = LABELS[m.group(1).lower()]
    if not kind:
        return None
    title = _PREFIX.sub("", title).strip()
    target = None
    if meta.get("research-claim"):
        target = {"kind": "claim", "name": meta["research-claim"].strip().rstrip(".,")}
    elif (t := _TARGET.search(body) or _TARGET.search(title)):
        what, val = t.group(1).lower(), t.group(2).strip().rstrip(".,")
        if what == "paper":
            try:
                val = arxiv_id(val)[0]
            except ResearchError:
                what = None
        target = {"kind": what, "name": val} if what else None
    text = _META.sub("", _TARGET.sub("", body))
    text = re.sub(r"\n\s*---\s*(\n|$)", "\n", text).strip()
    who = issue.get("author_association") or "NONE"
    ev = {"issue": issue.get("number"), "url": issue.get("html_url"), "kind": kind, "target": target,
          "title": title, "text": text[:2000], "author": (issue.get("user") or {}).get("login"),
          "association": who, "created": (issue.get("created_at") or "")[:10], "state": issue.get("state")}
    if meta.get("claim-file"):
        ev["claim_file"] = meta["claim-file"]
    if who not in TRUSTED:
        ev.update(applied=False, why="the author is not the repository's owner, a member or a collaborator")
    elif kind in ("prioritise", "reject", "dispute") and not target:
        ev.update(applied=False, why="no target: a `research-claim: NAME` line, or `claim: NAME`, `paper: ARXIV_ID`, "
                                     "`role: NAME` or `option: NAME` on a line of its own")
    else:
        ev["applied"] = True
    return ev


def fetch_issues(repo: str) -> list[dict]:
    """Open and closed issues with a research:* label or title prefix, through the GitHub CLI (`gh api`), which uses
    the harness's own login. Read-only."""
    out = subprocess.run(["gh", "api", "-X", "GET", f"repos/{repo}/issues", "-f", "state=all", "-f", "per_page=100",
                          "--paginate", "--jq", ".[]"], capture_output=True, text=True, check=True).stdout
    return [json.loads(line) for line in out.splitlines() if line.strip()]


def steer(p: Project, issues: list[dict]) -> list[dict]:
    """Record new steering events in research/steering.jsonl and apply them: a rejected paper is not read again; a
    question becomes a watch topic waiting for its terms. Prioritised and rejected claims are applied by `rank`."""
    have = {e["issue"] for e in p.steering()}
    new = [e for e in (parse_issue(i) for i in issues) if e and e["issue"] not in have]
    for e in new:
        e["recorded"] = today()
    p.dir.mkdir(exist_ok=True)
    (p.dir / "steering.jsonl").touch()
    if not new:
        return []
    seen = p.seen()
    for e in new:
        t = e.get("target") or {}
        if e["applied"] and e["kind"] == "reject" and t.get("kind") == "paper" and t["name"] in seen:
            seen[t["name"]].update(status="rejected", reason=f"steering, issue #{e['issue']}")
    p.save_seen(seen)
    qs = [e for e in new if e["applied"] and e["kind"] in TOPICAL]
    if qs:
        f = p.dir / "watch.yaml"
        w = load_yaml(f) or {}
        names = {t["name"] for t in w.get("topics") or []}
        add = ""
        for e in qs:
            name = f"issue-{e['issue']}"
            if name in names:
                continue
            add += (f"  - name: {name}   # from steering ({e['kind']}): fill in terms and roles, then it is watched\n"
                    f"    question: {json.dumps(e['title'] + ('. ' + e['text'] if e['text'] else ''))}\n"
                    f"    from: {json.dumps(e.get('url') or '')}\n"
                    f"    roles: []\n    terms: []\n")
        if add:
            txt = f.read_text()
            txt = txt.rstrip("\n") + "\n" + add
            f.write_text(txt)
    with (p.dir / "steering.jsonl").open("a") as fh:
        for e in new:
            fh.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")
    return new


# ------------------------------------------------------------------ rank

def entropy(p: float) -> float:
    """Bits of information in a yes-or-no outcome predicted at p: what a trial is expected to teach."""
    if p <= 0 or p >= 1:
        return 0.0
    return -(p * math.log2(p) + (1 - p) * math.log2(1 - p))


FUNDING_GAIN = 3.0   # a fully funded claim's score is multiplied by 1 + FUNDING_GAIN; the factor is capped there


def funding_factor(fraction: float) -> float:
    """1 + 3 x the fraction funded, the fraction capped at 1: unfunded x1, half funded x2.5, fully funded x4."""
    return 1 + FUNDING_GAIN * min(1.0, max(0.0, fraction))


def rank(p: Project) -> dict:
    """research/queue.json: the claims predicted for this system and not yet tested, ranked by what a trial would
    teach (the entropy of its prediction) for its cost, with steering applied; research/index.json: every claim, for
    a static site."""
    w = p.watch()
    system = backstage.parse_ref(w["system"], "system")
    steer_ev = [e for e in p.steering() if e.get("applied")]
    def targets(kind):
        return [e for e in steer_ev if e["kind"] == kind and e.get("target")]
    def hit(ev, name, doc):
        t = ev["target"]
        s = doc["spec"]
        return ((t["kind"] == "claim" and t["name"] == name)
                or (t["kind"] == "paper" and claim_key(doc)[0] == t["name"])
                or (t["kind"] == "role" and backstage.parse_ref(t["name"], "component") == s["role"])
                or (t["kind"] == "option" and backstage.parse_ref(t["name"], "component") ==
                    backstage.parse_ref(s["about"], "component")))
    fund = p.funding()
    rows, index = [], []
    for name, (f, doc) in sorted(p.claims().items()):
        s = doc["spec"]
        a = next((x for x in s.get("assessments") or [] if backstage.parse_ref(x["system"], "system") == system), None)
        rel = f.relative_to(p.root).as_posix()
        index.append({"name": name, "file": rel, "about": s["about"], "role": s["role"],
                      "source": {k: s["source"].get(k) for k in ("kind", "id", "title", "url")},
                      "statement": s["claim"]["statement"], "status": a["status"] if a else None,
                      "p_transfer": ((a or {}).get("prediction") or {}).get("p_transfer")})
        if not a or a["status"] != "predicted":
            continue
        rej = [e["issue"] for e in targets("reject") if hit(e, name, doc)]
        pri = [e["issue"] for e in targets("prioritise") if hit(e, name, doc)]
        dis = [e["issue"] for e in targets("dispute") if hit(e, name, doc)]
        pt = a["prediction"]["p_transfer"]
        trial = a.get("trial") or {}
        cost = float(trial.get("cost_hours") or 0) or None
        info = entropy(pt)
        fd = fund["funds"].get(name) or {}
        pledged, received = float(fd.get("pledged") or 0), float(fd.get("received") or 0)
        price = cost * fund["rate_per_hour"] if cost and fund["funds"] else None
        fraction = round(min(1.0, (pledged + received) / price), 4) if price and (pledged or received) else 0.0
        ready = bool(price and received >= price and not rej)
        score = None if rej or cost is None else round(info * (2 if pri else 1) * funding_factor(fraction) / cost, 4)
        rows.append({"claim": name, "file": rel, "role": s["role"], "about": s["about"], "p_transfer": pt,
                     "information_bits": round(info, 3), "cost_hours": cost, "plan": trial.get("plan"),
                     "prioritised_by": pri, "rejected_by": rej, "disputed_by": dis, "score": score,
                     "currency": fund["currency"], "cost_money": price, "pledged": pledged, "received": received,
                     "funded_fraction": fraction, "funding_source": fd.get("source"), "ready": ready,
                     "reason": a["prediction"]["reason"]})
    rows.sort(key=lambda r: (not r["ready"], r["score"] is None, -(r["score"] or 0), -r["p_transfer"], r["claim"]))
    queue = {"system": w["system"], "date": today(),
             "how": "score = bits of information in the outcome, H(p_transfer), times 2 if prioritised by "
                    "steering, times 1 + 3 x the fraction funded (research/funding.yaml: pledged plus received over the "
                    "trial's cost at rate_per_hour, at most 1), divided by the trial's cost in hours; rejected or "
                    "uncosted claims have no score. ready: received covers the whole cost; those come first",
             "queue": rows}
    p.dir.mkdir(exist_ok=True)
    (p.dir / "queue.json").write_text(json.dumps(queue, indent=1, ensure_ascii=False) + "\n")
    (p.dir / "index.json").write_text(json.dumps({"system": w["system"], "claims": index,
                                                  "seen": len(p.seen()), "steering": len(p.steering())},
                                                 indent=1, ensure_ascii=False) + "\n")
    return queue


# ------------------------------------------------------------------ check

def check(p: Project, cache: Path, fetch: bool = False, http: Http | None = None) -> list[str]:
    """Every claim against the schema; every checked arXiv quote against the paper's text (from the cache, or fetched
    again with fetch=True; skipped when neither). Returns the errors."""
    errors, v, checked, skipped = [], validator(), 0, 0
    for name, (f, doc) in p.claims().items():
        rel = f.relative_to(p.root).as_posix()
        errors += [f"{rel}: {e}" for e in schema_errors(doc, v)]
        src = doc["spec"]["source"]
        if src.get("quote_status") != "checked" or not str(src.get("id", "")).lower().startswith("arxiv:"):
            continue
        pid, ver = arxiv_id(src["id"])
        ver = src.get("version") or ver or "v1"
        txt = paper_text(pid, ver, cache)
        if txt is None and fetch:
            fetch_text(pid, ver, cache, http)
            txt = paper_text(pid, ver, cache)
        if txt is None:
            skipped += 1
            continue
        ok, _ = find_quote(src["quote"], *txt)
        checked += 1
        if not ok:
            errors.append(f"{rel}: quote not found in arXiv {pid}{ver}")
    print(f"claims: {len(p.claims())}; arXiv quotes matched: {checked}, not checked (no text cached): {skipped}")
    return errors


# ------------------------------------------------------------------ command line

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -I -m morphogen.research", description=__doc__.split("\n\n")[0])
    ap.add_argument("--cache", help="where papers are kept (untrusted input; outside the project)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for n in ("watch", "triage", "fetch", "catalog", "steer", "rank", "check"):
        s = sub.add_parser(n)
        s.add_argument("root", type=Path)
        if n == "watch":
            s.add_argument("--days", type=int, default=30)
            s.add_argument("--max", type=int, default=25)
        if n == "triage":
            s.add_argument("ids", nargs="+")
            s.add_argument("--status", required=True, choices=STATUSES)
            s.add_argument("--reason", required=True)
        if n == "fetch":
            s.add_argument("id")
        if n == "catalog":
            s.add_argument("draft", type=Path)
            s.add_argument("--by", default="research-loop agent draft; not yet reviewed by the owner")
        if n == "steer":
            g = s.add_mutually_exclusive_group(required=True)
            g.add_argument("--repo")
            g.add_argument("--issues", type=Path, help="a JSON list of issues (the REST API's shape)")
        if n == "check":
            s.add_argument("--fetch", action="store_true")
    a = ap.parse_args(argv)
    cache = cache_dir(a.cache)
    try:
        p = Project(a.root)
        if a.cmd == "watch":
            fresh = watch(p, a.days, a.max)
            for r in fresh:
                print(f"{r['id']}{r['version']}  [{', '.join(r['topics'])}]  {r['title']}\n    {r['abstract'][:400]}")
            print(f"{len(fresh)} new; research/seen.jsonl holds {len(p.seen())}")
        elif a.cmd == "triage":
            triage(p, a.ids, a.status, a.reason)
        elif a.cmd == "fetch":
            pid, ver = arxiv_id(a.id)
            ver = ver or (p.seen().get(pid) or {}).get("version") or "v1"
            rec = fetch_text(pid, ver, cache)
            d = cache / "papers" / f"{pid}{ver}"
            if (d / "text.md").exists():
                rec["text"] = str(d / "text.md")
                rec["chars"] = len((d / "text.md").read_text())
            print(json.dumps(rec, indent=1))
        elif a.cmd == "catalog":
            print(json.dumps(catalog(p, a.draft, cache, a.by), indent=1))
        elif a.cmd == "steer":
            issues = json.loads(a.issues.read_text()) if a.issues else fetch_issues(a.repo)
            for e in steer(p, issues):
                print(f"#{e['issue']} {e['kind']} {e.get('target')} applied={e['applied']} {e.get('why', '')}")
        elif a.cmd == "rank":
            q = rank(p)
            for r in q["queue"]:
                print(f"{r['score'] if r['score'] is not None else '-':>8}  p={r['p_transfer']:.2f}  "
                      f"{r['cost_hours'] or '?'} h  {r['claim']}")
        elif a.cmd == "check":
            errs = check(p, cache, a.fetch)
            for e in errs:
                print("ERROR", e)
            print("FAILED" if errs else "all checks pass")
            return 1 if errs else 0
    except (ResearchError, backstage.CatalogError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
