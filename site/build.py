"""Build the research agent's static site from the claim, role and option files.

    python3 site/build.py                       # site/config.toml in, site/_build out
    python3 site/build.py --out /tmp/site --config other.toml

Reads EvidenceClaim files (schemas/evidence-claim.v1.json) and the catalog's Backstage entity files, and writes
plain HTML, one CSS file, two small scripts and data/claims.json. No server, no database, nothing fetched at
runtime. Needs Python 3.11 and PyYAML; with jsonschema installed (it is in requirements.lock), every claim is
validated first and an invalid one stops the build.

Claim text comes from papers, so every string from a file is HTML-escaped where it is written (`e()`), and a link
from a file is written only when it is http or https (`safe_url()`).
"""

from __future__ import annotations

import argparse
import html
import json
import shutil
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

STATUSES = ["untested", "predicted", "replicated", "did-not-transfer", "not-testable"]
OBSERVATION = "observation"  # a claim of this system's own (source.kind trial or probe): it has no status
MIXED = "mixed"  # a claim whose assessments for the system disagree (one configuration replicated, another did not)
STATUS_TEXT = {
    "untested": "Untested",
    "predicted": "Predicted",
    "replicated": "Replicated",
    "did-not-transfer": "Did not transfer",
    "not-testable": "Not testable",
    OBSERVATION: "Our observation",
    MIXED: "Mixed",
}
STATUS_HELP = {
    "untested": "Catalogued, with the reason it has not been tried here.",
    "predicted": "A probability that it holds here was written before any outcome.",
    "replicated": "Tried on this system's setup, and the finding held.",
    "did-not-transfer": "Tried on this system's setup, and the finding did not hold.",
    "not-testable": "Cannot be tried here, and why.",
    OBSERVATION: "A measurement this system ran itself, which a paper's outcome links to.",
    MIXED: "Tried on more than one configuration, with different results.",
}
QUOTE_SHORT = {"checked": "quote checked", "unchecked": "quote unchecked", "none": "no quote"}
QUOTE_TEXT = {
    "checked": "Quote checked against the source",
    "unchecked": "Quote copied, not yet checked",
    "none": "No verbatim quote taken",
}


# ---------------------------------------------------------------- escaping and links


def e(value) -> str:
    """Escape any value for HTML text or a quoted attribute."""
    return html.escape("" if value is None else str(value), quote=True)


def safe_url(url) -> str | None:
    """The URL if it is http(s) with a host, else None: a file must not be able to write a javascript: link."""
    if not isinstance(url, str):
        return None
    url = url.strip()
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return url


def link(url, text, cls: str = "") -> str:
    """An external link when the URL is safe, plain text when it is not."""
    good = safe_url(url)
    if not good:
        return e(text)
    c = f' class="{e(cls)}"' if cls else ""
    return f'<a href="{e(good)}"{c} rel="noopener noreferrer">{e(text)}</a>'


def issue_url(repo: str, title: str, body: str, labels: list[str]) -> str:
    """A prefilled new-issue URL. GitHub reads `title`, `body` and comma-separated `labels` from the query."""
    query = {"title": title, "body": body}
    if labels:
        query["labels"] = ",".join(labels)
    return f"https://github.com/{quote(repo, safe='/')}/issues/new?" + urlencode(query, quote_via=quote)


# ---------------------------------------------------------------- loading


def ref_name(ref: str | None) -> str:
    """`component:default/decision-backend` -> `decision-backend`."""
    if not ref:
        return ""
    return ref.split(":", 1)[-1].split("/", 1)[-1]


@dataclass
class Claim:
    doc: dict
    path: str  # relative to the repository root

    @property
    def name(self) -> str:
        return self.doc["metadata"]["name"]

    @property
    def spec(self) -> dict:
        return self.doc["spec"]

    @property
    def source(self) -> dict:
        return self.spec["source"]

    @property
    def ours(self) -> bool:
        return self.source.get("kind") in ("trial", "probe")

    def assessments(self, system: str) -> list[dict]:
        """Every assessment for the system: one per configuration tried (a model, an engine), and they can disagree."""
        return [a for a in self.spec.get("assessments") or [] if a.get("system") == system]

    def predictions(self, system: str) -> list[dict]:
        return [a["prediction"] for a in self.assessments(system) if a.get("prediction")]

    def statuses(self, system: str) -> list[str]:
        """The distinct statuses of its assessments, in file order; a filter matches a claim on any of them."""
        if self.ours:
            return [OBSERVATION]
        out = []
        for a in self.assessments(system):
            if a["status"] not in out:
                out.append(a["status"])
        return out or ["untested"]

    def status(self, system: str) -> str:
        """One status, or `mixed` when its assessments disagree (statuses() and the badges give the breakdown)."""
        statuses = self.statuses(system)
        return statuses[0] if len(statuses) == 1 else MIXED

    def date(self) -> str:
        dates = []
        for a in self.spec.get("assessments") or []:
            dates += [a.get("date"), (a.get("prediction") or {}).get("date"), (a.get("outcome") or {}).get("date")]
        return max((str(d) for d in dates if d), default="")


@dataclass
class Catalog:
    entities: list[dict] = field(default_factory=list)

    def of(self, kind: str) -> list[dict]:
        return [x for x in self.entities if x.get("kind") == kind]

    def get(self, ref: str) -> dict | None:
        name = ref_name(ref)
        for x in self.entities:
            if x.get("metadata", {}).get("name") == name and x.get("kind") != "Location":
                return x
        return None

    @property
    def roles(self) -> list[dict]:
        return [x for x in self.of("Component") if (x.get("spec") or {}).get("type") == "role"]

    @property
    def options(self) -> list[dict]:
        return [x for x in self.of("Component") if (x.get("spec") or {}).get("lifecycle") == "candidate"]

    @property
    def conditions(self) -> list[dict]:
        return self.of("Resource")

    @property
    def system(self) -> dict | None:
        systems = self.of("System")
        return systems[0] if systems else None


def load_yaml_docs(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return [d for d in yaml.safe_load_all(f) if isinstance(d, dict)]


def load_claims(dirs: list[Path], root: Path, schema: dict | None) -> list[Claim]:
    validator = None
    if schema is not None:
        try:
            import jsonschema  # noqa: PLC0415
        except ImportError:
            print("build: jsonschema is not installed; claims are not validated", file=sys.stderr)
        else:
            cls = jsonschema.validators.validator_for(schema)
            validator = cls(schema, format_checker=cls.FORMAT_CHECKER)
    claims, seen = [], {}
    for d in dirs:
        for path in sorted(list(d.rglob("*.yaml")) + list(d.rglob("*.yml"))):
            for doc in load_yaml_docs(path):
                if doc.get("kind") != "EvidenceClaim":
                    continue
                rel = path.resolve().relative_to(root).as_posix() if path.resolve().is_relative_to(root) else path.name
                if validator is not None:
                    errors = sorted(validator.iter_errors(_jsonable(doc)), key=lambda x: list(x.path))
                    if errors:
                        where = "/".join(str(p) for p in errors[0].path)
                        raise SystemExit(f"build: {rel} is not a valid EvidenceClaim: {where}: {errors[0].message}")
                claim = Claim(doc, rel)
                if claim.name in seen:
                    raise SystemExit(f"build: claim name {claim.name} is in both {seen[claim.name]} and {rel}")
                seen[claim.name] = rel
                claims.append(claim)
    return claims


def _jsonable(value):
    """YAML gives dates as date objects; the schema and JSON want strings."""
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def sort_claims(claims: list[Claim]) -> list[Claim]:
    """Newest first: the latest assessment, prediction or outcome date; then the source id (arXiv ids grow)."""
    return sorted(claims, key=lambda c: (c.date(), str(c.source.get("id", "")), c.name), reverse=True)


# ---------------------------------------------------------------- formatting values


def fmt_number(value) -> str:
    if value is None:
        return "not stated"
    if isinstance(value, dict):
        over = f" over {value['over']}" if value.get("over") else ""
        return f"{value.get('min')} to {value.get('max')}{over}"
    return str(value)


def fmt_interval(iv: dict | None) -> str:
    if not iv:
        return ""
    how = [f"{round(iv['level'] * 100)}%" if iv.get("level") else "", iv.get("method", "")]
    how = ", ".join(x for x in how if x)
    return f"[{iv.get('low')}, {iv.get('high')}]" + (f" ({how})" if how else "")


def measure_html(m: dict) -> str:
    """One measure as a definition list row group."""
    better = {"higher": "higher is better", "lower": "lower is better"}.get(m.get("better", ""), "")
    unit = f" {m['unit']}" if m.get("unit") else ""
    value = fmt_number(m.get("value")) + (unit if m.get("value") is not None else "")
    rows = [("Metric", m.get("metric", "") + (f" ({better})" if better else ""))]
    rows.append(("Value", value + (" " + fmt_interval(m.get("interval")) if m.get("interval") else "")))
    if m.get("where"):
        rows.append(("Where", m["where"]))
    b = m.get("baseline")
    if b:
        bv = b.get("value")
        bval = "" if bv is None else f": {fmt_number(bv)}"
        rows.append(("Against", f"{b.get('name', '')}{bval}" + (" " + fmt_interval(b.get("interval")) if b.get(
            "interval") else "")))
    return "".join(f"<dt>{e(k)}</dt><dd>{e(v)}</dd>" for k, v in rows)


def status_badge(status: str) -> str:
    return f'<span class="badge s-{e(status)}" title="{e(STATUS_HELP.get(status, ""))}">{e(STATUS_TEXT.get(status, status))}</span>'


def meter(p: float, label: bool = True) -> str:
    """The transfer probability as a bar, with the number beside it (never the bar alone)."""
    pct = max(0.0, min(1.0, float(p))) * 100
    bar = (f'<svg class="meter" viewBox="0 0 100 8" preserveAspectRatio="none" aria-hidden="true" focusable="false">'
           f'<rect class="meter-track" x="0" y="0" width="100" height="8" rx="4"/>'
           f'<rect class="meter-fill" x="0" y="0" width="{pct:.1f}" height="8" rx="4"/></svg>')
    text = f'<span class="meter-num">p&nbsp;{float(p):.2f}</span>' if label else ""
    return f'<span class="meter-wrap" title="Predicted probability the finding holds here">{bar}{text}</span>'


def source_short(src: dict) -> str:
    return src.get("id") or src.get("title", "")


def truncate(text: str, n: int) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


# ---------------------------------------------------------------- page frame


@dataclass
class Site:
    title: str
    repo: str
    branch: str
    system: str
    labels: dict
    claims: list[Claim]
    catalog: Catalog
    research: dict = field(default_factory=dict)  # the agent's queue.json, watch.yaml, seen.jsonl (load_research)

    def queue(self) -> list[dict]:
        return list((self.research.get("queue") or {}).get("queue") or [])

    def queue_rank(self, name: str) -> tuple[int, dict] | None:
        for i, item in enumerate(self.queue(), 1):
            if item.get("claim") == name:
                return i, item
        return None

    def config_label(self, a: dict) -> str:
        """The configuration an assessment was made on, in a few words: the models among its `against` resources
        (their description up to the first comma, as in "Inkling 2 Mini"), else every resource's name."""
        names = []
        for ref in a.get("against") or []:
            res = self.catalog.get(ref)
            if res and (res.get("spec") or {}).get("type") == "model":
                head = (res["metadata"].get("description") or "").split(",")[0].strip()
                names.append(head if head and len(head) <= 40 else res["metadata"]["name"])
        if not names:
            names = [ref_name(r) for r in a.get("against") or []]
        return ", ".join(names)

    def status_badges(self, c: Claim) -> str:
        """One badge when the assessments agree; when they disagree, a Mixed badge and one per configuration."""
        assessments = c.assessments(self.system)
        if c.ours or len(c.statuses(self.system)) == 1:
            return status_badge(c.status(self.system))
        parts = [status_badge(MIXED)]
        for a in assessments:
            label = self.config_label(a)
            parts.append(f'<span class="cfg">{status_badge(a["status"])}'
                         f'{f" <span class=small>{e(label)}</span>" if label else ""}</span>')
        return "".join(parts)

    def status_text(self, c: Claim) -> str:
        """The same breakdown in words, for an issue body: `replicated (Inkling 2 Mini); did-not-transfer (LFM3 1.7B)`."""
        if c.ours or len(c.statuses(self.system)) == 1:
            return c.status(self.system)
        return "; ".join(f"{a['status']} ({self.config_label(a) or 'unnamed configuration'})"
                         for a in c.assessments(self.system))

    def by_name(self) -> dict[str, Claim]:
        return {c.name: c for c in self.claims}

    def file_url(self, path: str) -> str:
        return f"https://github.com/{self.repo}/blob/{self.branch}/{path}"

    def issue(self, action: str, title: str, body: str) -> str:
        return issue_url(self.repo, title, body, list(self.labels.get(action, [])))


NAV = [("index.html", "Claims"), ("queue.html", "Next to test"), ("predictions.html", "Predictions"), ("roles.html", "Roles"), ("how.html", "How it works")]


def page(site: Site, title: str, body: str, current: str, depth: int = 0, description: str = "") -> str:
    up = "../" * depth
    nav = "".join(
        f'<li><a href="{up}{href}"{" aria-current=page" if href == current else ""}>{e(text)}</a></li>'
        for href, text in NAV)
    full_title = f"{title} · {site.title}" if title != site.title else site.title
    desc = description or "Claims from papers about options for the system's roles, with conditions, transfer predictions and outcomes."
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'">
<meta name="referrer" content="no-referrer">
<meta name="description" content="{e(desc)}">
<meta name="color-scheme" content="light dark">
<title>{e(full_title)}</title>
<link rel="icon" href="{up}assets/icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="{up}assets/style.css">
<script src="{up}assets/theme.js"></script>
</head>
<body>
<a class="skip" href="#main">Skip to content</a>
<header class="top">
  <div class="top-in">
    <a class="brand" href="{up}index.html"><span class="brand-mark" aria-hidden="true">◇</span> Morphogen <span class="brand-sub">research</span></a>
    <nav aria-label="Site"><ul>{nav}</ul></nav>
    <button class="theme" type="button" data-theme-toggle aria-label="Colour theme: system">Auto</button>
  </div>
</header>
<main id="main" class="wrap">
{body}
</main>
<footer class="foot wrap">
  <p>Built from the claim, role and option files in {link(f"https://github.com/{site.repo}", site.repo)}. Static files only: no tracking, no cookies, nothing loaded from elsewhere. Steering happens in GitHub issues.</p>
</footer>
</body>
</html>
"""


# ---------------------------------------------------------------- the feed


def feed_item(site: Site, c: Claim) -> str:
    statuses = c.statuses(site.system)
    src, cl = c.source, c.spec["claim"]
    role, option = ref_name(c.spec.get("role")), ref_name(c.spec.get("about"))
    search = " ".join(str(x) for x in [c.name, c.doc["metadata"].get("description", ""), cl.get("statement", ""),
                                        src.get("title", ""), src.get("id", ""), role, option, cl.get("metric", "")])
    quote_cls = "q-" + src.get("quote_status", "none")
    meta = [f'<span class="mono">{e(source_short(src))}</span>', f'<span>{e(role)}</span>',
            f'<span>option <span class="mono">{e(option)}</span></span>']
    if c.date():
        meta.append(f'<time datetime="{e(c.date())}">{e(c.date())}</time>')
    right = "".join(meter(pr["p_transfer"]) for pr in c.predictions(site.system))
    return f"""<li class="item" data-name="{e(c.name)}" data-status="{e(" ".join(statuses))}" data-role="{e(role)}" data-source="{e(source_short(src))}" data-search="{e(search.lower())}">
  <article class="card">
    <div class="card-top">{site.status_badges(c)}<span class="qs {e(quote_cls)}" title="{e(QUOTE_TEXT.get(src.get('quote_status', 'none'), ''))}">{e(QUOTE_SHORT.get(src.get('quote_status', 'none'), ''))}</span>{right}</div>
    <h3><a href="claims/{e(c.name)}.html">{e(c.doc['metadata'].get('description') or cl.get('statement', c.name))}</a></h3>
    <p class="meta">{' <span aria-hidden="true">·</span> '.join(meta)}</p>
  </article>
</li>"""


def render_index(site: Site) -> str:
    claims = sort_claims(site.claims)
    counts = {s: 0 for s in STATUSES + [OBSERVATION]}
    for c in claims:  # a claim counts under each status any of its assessments has, as the filter matches it
        for st in c.statuses(site.system):
            counts[st] = counts.get(st, 0) + 1
    roles = sorted({ref_name(c.spec.get("role")) for c in claims})
    sources = {}
    for c in claims:
        sources.setdefault(source_short(c.source), c.source.get("title", ""))
    stat = "".join(
        f'<li><span class="stat-n">{counts[s]}</span> {status_badge(s)}</li>' for s in STATUSES + [OBSERVATION]
        if counts.get(s))
    status_boxes = "".join(
        f'<label class="chk"><input type="checkbox" name="status" value="{e(s)}"{"" if s == OBSERVATION else " checked"}> {e(STATUS_TEXT[s])} <span class="n">{counts.get(s, 0)}</span></label>'
        for s in STATUSES + [OBSERVATION])
    role_opts = "".join(f'<option value="{e(r)}">{e(r)}</option>' for r in roles)
    src_opts = "".join(
        f'<option value="{e(k)}">{e(truncate(k + (" · " + v if v and v != k else ""), 70))}</option>'
        for k, v in sorted(sources.items(), reverse=True))
    items = "\n".join(feed_item(site, c) for c in claims)
    paper_n = sum(1 for c in claims if not c.ours)
    question = site.issue("question", "Question to watch: ", issue_body("question", site, None, extra=[
        "What should the research agent look for? A method, a role, an open question from the system's docs.", "",
        "Question:", "", "Why it matters here:", ""]))
    body = f"""
<section class="hero">
  <p class="eyebrow">The research agent's catalog</p>
  <h1>Claims from papers, checked against this system</h1>
  <p class="lede">The agent reads new papers for the roles in the map, writes down each claimed gain with the conditions it was measured under, and predicts whether it will hold here. Trials behind the judge then score the prediction. {paper_n} claims from papers so far, for <span class="mono">{e(ref_name(site.system))}</span>.</p>
  <ul class="stats" aria-label="Claims by status">{stat}</ul>
  <p class="actions"><a class="btn" href="{e(question)}" rel="noopener noreferrer">Propose a question to watch</a> <a class="btn ghost" href="how.html">How it works</a></p>
</section>

<form id="filters" class="filters" hidden role="search" aria-label="Filter claims">
  <div class="f-row">
    <label class="f-search"><span class="sr">Search</span><input type="search" name="q" placeholder="Search claims, models, metrics…" autocomplete="off"></label>
    <label><span class="f-lab">Role</span><select name="role"><option value="">All roles</option>{role_opts}</select></label>
    <label><span class="f-lab">Source</span><select name="source"><option value="">All sources</option>{src_opts}</select></label>
  </div>
  <fieldset class="f-row f-status"><legend class="f-lab">Status</legend>{status_boxes}</fieldset>
</form>
<p class="count" id="count" aria-live="polite"></p>
<ol class="feed" id="claims">
{items}
</ol>
<p class="empty" id="empty" hidden>No claim matches these filters.</p>
<script src="assets/app.js"></script>
"""
    return page(site, site.title, body, "index.html")


# ---------------------------------------------------------------- one claim


def issue_body(action: str, site: Site, c: Claim | None, extra: list[str] | None = None) -> str:
    """The body of a steering issue. Only the claim's name and path go in, never text from the paper: an issue
    body is rendered as Markdown, and a paper's words could mention people or carry links."""
    lines = []
    lines += extra or []
    lines += ["", "---", f"research-action: {action}", f"system: {site.system}"]
    if c is not None:
        lines += [f"research-claim: {c.name}", f"claim-file: {site.file_url(c.path)}",
                  f"status: {site.status_text(c)}"]
        preds = c.predictions(site.system)
        if len(preds) == 1:
            lines.append(f"p_transfer: {preds[0]['p_transfer']}")
    return "\n".join(lines).strip() + "\n"


def claim_actions(site: Site, c: Claim) -> str:
    if c.ours:
        return ""
    btns = [
        ("prioritise", f"Prioritise: {c.name}", "Test this claim next",
         ["Please test this claim sooner.", "", "Why it is worth a trial now:", ""]),
        ("reject", f"Reject: {c.name}", "Reject it",
         ["Please drop this claim from the queue.", "", "Why (does not apply here, already known, not a real gain):",
          ""]),
    ]
    if c.predictions(site.system):
        btns.append(("dispute", f"Dispute prediction: {c.name}", "Dispute the prediction",
                     ["I think the transfer prediction is wrong.", "", "My probability that it holds here:", "",
                      "Which conditions it gets wrong:", ""]))
    out = []
    for action, title, text, extra in btns:
        url = site.issue(action, title, issue_body(action, site, c, extra))
        cls = "btn" if action == "prioritise" else "btn ghost"
        out.append(f'<a class="{cls}" href="{e(url)}" rel="noopener noreferrer">{e(text)}</a>')
    labels = ", ".join(sorted({lab for k in ("prioritise", "reject", "dispute") for lab in site.labels.get(k, [])}))
    return f"""<section class="steer" aria-labelledby="steer-h">
  <h2 id="steer-h">Steer the agent</h2>
  <p>Each button opens a new GitHub issue, filled in, for you to edit and submit. The agent reads issues labelled {e(labels)}.</p>
  <p class="actions">{" ".join(out)}</p>
</section>"""


def quote_html(src: dict) -> str:
    status = src.get("quote_status", "none")
    head = f'<p class="qhead"><span class="qs q-{e(status)}">{e(QUOTE_TEXT.get(status, status))}</span>'
    if src.get("quote_location"):
        head += f' <span class="muted">{e(src["quote_location"])}</span>'
    head += "</p>"
    parts = [head]
    if src.get("quote"):
        parts.append(f'<blockquote class="verbatim"><p>{e(src["quote"])}</p></blockquote>')
    if src.get("quote_note"):
        parts.append(f'<p class="muted small">{e(src["quote_note"])}</p>')
    via = src.get("via")
    if via:
        where = f", {via['location']}" if via.get("location") else ""
        parts.append(f'<p class="qhead"><span class="qs q-via">Via a secondary source</span> '
                     f'{link(via.get("url"), via.get("title", ""))}<span class="muted">{e(where)}</span></p>')
        parts.append(f'<blockquote class="verbatim via"><p>{e(via.get("quote", ""))}</p></blockquote>')
    return "".join(parts)


def conditions_html(cond: dict) -> str:
    rows = []
    models = cond.get("models") or []
    if models:
        items = []
        for m in models:
            bits = [m.get(k) for k in ("size", "precision", "tuned") if m.get(k)]
            items.append(f'<li><strong>{e(m.get("name", ""))}</strong>'
                         + (f' <span class="muted">{e(", ".join(bits))}</span>' if bits else "")
                         + (f'<br><span class="muted small">{e(m["capability"])}</span>' if m.get("capability") else "")
                         + "</li>")
        rows.append(("Models", f'<ul class="plain">{"".join(items)}</ul>'))
    for key, label in (("engine", "Engine"), ("dataset", "Dataset"), ("hardware", "Hardware")):
        v = cond.get(key)
        if isinstance(v, dict):
            text = ", ".join(str(v[k]) for k in ("name", "version", "split", "size", "memory") if v.get(k))
            rows.append((label, e(text)))
    for key, label in (("method", "Method"), ("thinking", "Thinking"), ("labels", "Labels")):
        if cond.get(key):
            rows.append((label, e(cond[key])))
    known = {"models", "engine", "dataset", "hardware", "method", "thinking", "labels", "unstated"}
    for key, v in cond.items():
        if key not in known and v not in (None, "", [], {}):
            rows.append((key.replace("_", " ").capitalize(), e(v if isinstance(v, str) else json.dumps(_jsonable(v)))))
    if cond.get("unstated"):
        rows.append(("Not stated", '<ul class="plain unstated">' + "".join(
            f"<li>{e(u)}</li>" for u in cond["unstated"]) + "</ul>"))
    return '<dl class="kv">' + "".join(f"<dt>{e(k)}</dt><dd>{v}</dd>" for k, v in rows) + "</dl>"


def claim_ref(site: Site, name: str, depth: int) -> str:
    c = site.by_name().get(name)
    up = "../" * depth
    if not c:
        return f'<span class="mono">{e(name)}</span>'
    return (f'<a href="{up}claims/{e(name)}.html" class="mono">{e(name)}</a>'
            f' <span class="muted small">{e(truncate(c.doc["metadata"].get("description", ""), 110))}</span>')


def assessment_html(site: Site, c: Claim, a: dict) -> str:
    label = site.config_label(a)
    parts = [f'<div class="assess"><p class="assess-head">{status_badge(a["status"])}'
             + (f' on <strong>{e(label)}</strong>' if label else "")
             + f' for <span class="mono">{e(a.get("system"))}</span>'
             + (f' <span class="muted">on {e(a["date"])}</span>' if a.get("date") else "") + "</p>"]
    if a.get("against"):
        parts.append('<p class="small muted">Compared with: ' + ", ".join(
            f'<a class="mono" href="../roles.html#{e(ref_name(r))}">{e(ref_name(r))}</a>' for r in a["against"]) + "</p>")
    pr = a.get("prediction")
    if pr:
        parts.append(f"""<div class="pred"><h3>Transfer prediction</h3>
<p class="pred-p">{meter(pr["p_transfer"])}</p>
<p>{e(pr.get("reason", ""))}</p>
<p class="small muted">By {e(pr.get("by", ""))}, {e(pr.get("date", ""))}. {"Written before any outcome, so it counts towards calibration." if pr.get("before_outcome") else "Written after an outcome was seen, so it does not count towards calibration."}</p></div>""")
    plan = a.get("trial")
    if plan:
        needs = "".join(f"<li>{e(n)}</li>" for n in plan.get("needs") or [])
        code = f"<dt>Code</dt><dd>{link(plan.get('code'), plan.get('code', ''))}</dd>" if plan.get("code") else ""
        ranked = site.queue_rank(c.name)
        rank = (f'<p class="small">Number {ranked[0]} of {len(site.queue())} in the <a href="../queue.html">queue</a>.</p>'
                if ranked else "")
        parts.append(f"""<div class="pred"><h3>The cheapest trial that would settle it</h3>
<p>{e(plan.get("plan", ""))}</p>
<dl class="kv"><dt>Cost</dt><dd>about {e(plan.get("cost_hours"))} hours, setting up included</dd>{f'<dt>Needs</dt><dd><ul class="plain">{needs}</ul></dd>' if needs else ""}{code}</dl>{rank}</div>""")
    out = a.get("outcome")
    if out:
        t = out.get("trial") or {}
        v = out.get("verdict") or {}
        observed = "".join(f"<li>{claim_ref(site, n, 1)}</li>" for n in out.get("observed") or [])
        by = {"morphogen": "the judge", "falsifier": "a falsifier registered before the outcome",
              "operator": "the operator", "none": "nobody yet"}.get(v.get("by"), v.get("by", ""))
        parts.append(f"""<div class="outcome"><h3>Outcome</h3>
<p>Trial {link(t.get("url"), t.get("id", ""), "mono")}{(" · " + e(out["date"])) if out.get("date") else ""} · {e("a transfer test on our setup" if out.get("comparison") == "our-setup" else "the source's own setup reproduced")}</p>
<p>{e(out.get("summary", ""))}</p>
<dl class="kv"><dt>Verdict</dt><dd><strong>{e(v.get("decision", ""))}</strong>, decided by {e(by)}{(" <span class='muted small mono'>" + e(v["ref"]) + "</span>") if v.get("ref") else ""}{("<br><span class='small'>" + e(v["note"]) + "</span>") if v.get("note") else ""}</dd>
<dt>Observed</dt><dd><ul class="plain">{observed}</ul></dd></dl></div>""")
    if a.get("reason"):
        parts.append(f'<p><span class="f-lab">Note</span><br>{e(a["reason"])}</p>')
    if a.get("see_also"):
        parts.append('<p class="f-lab">See also</p><ul class="plain">' + "".join(
            f"<li>{claim_ref(site, n, 1)}</li>" for n in a["see_also"]) + "</ul>")
    parts.append("</div>")
    return "".join(parts)


def render_claim(site: Site, c: Claim) -> str:
    md, src, cl, cond = c.doc["metadata"], c.source, c.spec["claim"], c.spec.get("conditions") or {}
    status = c.status(site.system)
    option = site.catalog.get(c.spec.get("about", ""))
    role = site.catalog.get(c.spec.get("role", ""))
    reporting = {"self": "the source measures its own method", "independent": "the source measures methods it did not make",
                 "ours": "this system's own trial", "unknown": "not stated who measured it"}.get(cl.get("reporting"), "")
    effect = cl.get("effect_size")
    effect_html = (f"<dt>Effect</dt><dd>{e(fmt_number(effect.get('value')))} ({e(effect.get('kind'))})"
                   f"{(' · ' + e(effect['note'])) if effect.get('note') else ''}</dd>") if effect else (
        "<dt>Effect</dt><dd class='muted'>No effect size stated (a difference of two stated numbers is not one)</dd>")
    strength = [f"<dt>Finding</dt><dd><strong>{e(cl.get('finding'))}</strong> against the baseline</dd>", effect_html]
    if cl.get("significance"):
        strength.append(f"<dt>Significance</dt><dd>{e(cl['significance'])}</dd>")
    strength.append(f"<dt>Runs · cases</dt><dd>{e(cl.get('runs') if cl.get('runs') is not None else 'not stated')} · "
                    f"{e(cl.get('cases') if cl.get('cases') is not None else 'not stated')}</dd>")
    strength.append(f"<dt>Reported by</dt><dd>{e(cl.get('reporting'))}: {e(reporting)}</dd>")
    also = "".join(f'<dl class="kv also">{measure_html(m)}</dl>' for m in cl.get("also") or [])
    if also:
        also = "<h3>Also measured</h3>" + also
    if cl.get("note"):
        also += f'<p class="muted small">{e(cl["note"])}</p>'
    src_bits = [x for x in (src.get("id"), src.get("version") and f"version {src['version']}") if x]
    assessments = "".join(assessment_html(site, c, a) for a in c.spec.get("assessments") or [])
    if not assessments and c.ours:
        linked = [o for o in site.claims for a in o.spec.get("assessments") or []
                  for n in ((a.get("outcome") or {}).get("observed") or []) + (a.get("see_also") or []) if n == c.name]
        names = sorted({o.name for o in linked})
        assessments = ('<p>This is a measurement this system ran. Claims from papers that it bears on:</p><ul class="plain">'
                       + "".join(f"<li>{claim_ref(site, n, 1)}</li>" for n in names) + "</ul>") if names else (
            "<p>This is a measurement this system ran. No paper's claim links to it yet.</p>")
    body = f"""
<p class="crumbs"><a href="../index.html">Claims</a> <span aria-hidden="true">/</span> <span class="mono">{e(c.name)}</span></p>
<article class="claim">
  <header class="claim-head">
    <div class="card-top">{site.status_badges(c)}<span class="mono muted">{e(ref_name(c.spec.get("role")))} · option {e(ref_name(c.spec.get("about")))}</span></div>
    <h1>{e(md.get("description") or c.name)}</h1>
    <p class="statement">{e(cl.get("statement", ""))}</p>
  </header>

  <section aria-labelledby="src-h" class="panel">
    <h2 id="src-h">Source</h2>
    <p><strong>{link(src.get("url"), src.get("title", ""))}</strong><br><span class="mono small">{e(" · ".join(src_bits))}</span> <span class="muted small">({e(src.get("kind"))})</span></p>
    <dl class="kv"><dt>Where</dt><dd>{e(src.get("location", ""))}</dd><dt>Read</dt><dd>{e(src.get("read", ""))}</dd></dl>
    {quote_html(src)}
  </section>

  <div class="cols">
    <section aria-labelledby="m-h" class="panel">
      <h2 id="m-h">Measure and effect</h2>
      <dl class="kv">{measure_html(cl)}{"".join(strength)}</dl>
      {also}
    </section>
    <section aria-labelledby="c-h" class="panel">
      <h2 id="c-h">Conditions</h2>
      {conditions_html(cond)}
    </section>
  </div>

  <section aria-labelledby="a-h" class="panel">
    <h2 id="a-h">{"Status here" if not c.ours else "Where it is used"}</h2>
    {assessments}
  </section>

  {option_panel(option, role)}
  {claim_actions(site, c)}
  <p class="small muted">The record: {link(site.file_url(c.path), c.path, "mono")}</p>
</article>
"""
    return page(site, md.get("description") or c.name, body, "", depth=1, description=truncate(cl.get("statement", ""), 160))


def option_panel(option: dict | None, role: dict | None) -> str:
    if not option:
        return ""
    ev = ((option.get("spec") or {}).get("morphogen") or {}).get("evaluation") or {}
    rows = "".join(f"<dt>{e(k)}</dt><dd>{e(ev[key])}</dd>" for key, k in (("need", "What would count"),
                                                                        ("method", "How it is measured"),
                                                                        ("result", "Result so far")) if ev.get(key))
    rname = (role or {}).get("metadata", {}).get("name", "")
    name = option["metadata"]["name"]
    return f"""<section class="panel" aria-labelledby="o-h"><h2 id="o-h">The option</h2>
<p><a class="mono" href="../roles.html#{e(name)}">{e(name)}</a>, a candidate for the role <a class="mono" href="../roles.html#{e(rname)}">{e(rname)}</a>.</p>
<p>{e(option["metadata"].get("description", ""))}</p>{f'<dl class="kv">{rows}</dl>' if rows else ""}</section>"""


# ---------------------------------------------------------------- roles


def fills(option: dict) -> list[str]:
    """The roles an option fills: `spec.morphogen.fills`, one ref or a list."""
    f = ((option.get("spec") or {}).get("morphogen") or {}).get("fills") or []
    return [ref_name(r) for r in ([f] if isinstance(f, str) else f)]


def parse_evidence(annotation: str | None) -> list[tuple[str, str]]:
    """`stated | repo@commit:path | "quote"` lines -> (source, quote)."""
    out = []
    for line in (annotation or "").splitlines():
        parts = [p.strip() for p in line.split("|", 2)]
        if len(parts) == 3:
            out.append((parts[1], parts[2].strip('"')))
    return out


def render_roles(site: Site) -> str:
    cat = site.catalog
    claims_by_option: dict[str, list[Claim]] = {}
    for c in site.claims:
        if not c.ours:
            claims_by_option.setdefault(ref_name(c.spec.get("about")), []).append(c)
    blocks = []
    for r in cat.roles:
        name = r["metadata"]["name"]
        parent = (r.get("spec") or {}).get("subcomponentOf")
        ev = parse_evidence((r["metadata"].get("annotations") or {}).get("morphogen.dev/evidence"))
        ev_html = "".join(f'<blockquote class="verbatim small"><p>{e(q)}</p><footer class="mono muted">{e(s)}</footer></blockquote>'
                          for s, q in ev)
        opts = [o for o in cat.options if name in fills(o)]
        rows = []
        for o in opts:
            oname = o["metadata"]["name"]
            cs = claims_by_option.get(oname, [])
            counts = {}
            for c in cs:
                for st in c.statuses(site.system):
                    counts[st] = counts.get(st, 0) + 1
            badges = " ".join(f"{status_badge(s)}<span class='n'>×{n}</span>" for s, n in counts.items())
            result = (((o.get("spec") or {}).get("morphogen") or {}).get("evaluation") or {}).get("result")
            links = "".join(f'<li><a href="claims/{e(c.name)}.html">{e(truncate(c.doc["metadata"].get("description", c.name), 120))}</a></li>' for c in cs)
            rows.append(f"""<li class="opt" id="{e(oname)}"><h4 class="mono">{e(oname)}</h4><p>{e(o["metadata"].get("description", ""))}</p>
<p class="small">{badges or "<span class='muted'>No claims from papers yet</span>"}</p>{f'<p class="small"><span class="f-lab">Result so far</span> {e(result)}</p>' if result else ""}
{f'<details><summary>{len(cs)} claim{"s" if len(cs) != 1 else ""}</summary><ul class="plain">{links}</ul></details>' if cs else ""}</li>""")
        propose = site.issue("propose-option", f"Option to watch for {name}: ", issue_body("propose-option", site, None, extra=[
            f"An option, paper or method the research agent should look at for the role `{name}`.", "",
            "Option or paper:", "", "Why it might help here:", "", f"role: {name}"]))
        blocks.append(f"""<section class="role panel" id="{e(name)}" aria-labelledby="r-{e(name)}">
<p class="eyebrow">Role{f' · part of <a class="mono" href="#{e(parent)}">{e(parent)}</a>' if parent else ""}</p>
<h2 id="r-{e(name)}" class="mono">{e(name)}</h2>
<p>{e(r["metadata"].get("description", ""))}</p>{ev_html}
<h3>Options the agent is tracking ({len(opts)})</h3>
<ul class="opts">{"".join(rows) or "<li class='muted'>None yet.</li>"}</ul>
<p class="actions"><a class="btn ghost" href="{e(propose)}" rel="noopener noreferrer">Suggest an option for this role</a></p>
</section>""")
    conds = []
    for res in cat.conditions:
        n = res["metadata"]["name"]
        conds.append(f'<li id="{e(n)}"><span class="mono">{e(n)}</span> <span class="tag">{e((res.get("spec") or {}).get("type", ""))}</span><br><span class="small">{e(res["metadata"].get("description", ""))}</span></li>')
    system = cat.system
    sysdesc = e(system["metadata"].get("description", "")) if system else ""
    new_role = site.issue("propose-role", "Role to watch: ", issue_body("propose-role", site, None, extra=[
        "A part of the system the research agent should read papers for.", "", "The part, and what it does:", "",
        "What a better option would improve:", ""]))
    body = f"""
<section class="hero small-hero">
  <p class="eyebrow">What the agent watches for</p>
  <h1>Roles, from the map</h1>
  <p class="lede">The agent does not read a general feed. It looks for papers about the roles in the system's map, and every option it catalogues is a candidate for one of them. {sysdesc}</p>
  <p class="actions"><a class="btn" href="{e(new_role)}" rel="noopener noreferrer">Propose a role to watch</a></p>
</section>
{watch_html(site)}
{"".join(blocks)}
<section class="panel" aria-labelledby="cond-h"><h2 id="cond-h">This system's conditions</h2>
<p>Every claim's conditions are compared with these when its transfer is predicted.</p>
<ul class="plain conds">{"".join(conds)}</ul></section>
"""
    return page(site, "Roles", body, "roles.html")


# ---------------------------------------------------------------- predictions and calibration


def calibration_pairs(site: Site) -> list[tuple[float, int, Claim, dict]]:
    """(p, held, claim, assessment) for each assessment whose prediction was written before an outcome it now has.
    Each assessment counts on its own: a claim tried on two configurations is two predictions."""
    out = []
    for c in site.claims:
        for a in c.assessments(site.system):
            pr, status = a.get("prediction") or {}, a.get("status")
            if pr.get("before_outcome") and a.get("outcome") and status in ("replicated", "did-not-transfer"):
                out.append((float(pr["p_transfer"]), 1 if status == "replicated" else 0, c, a))
    return out


def brier(pairs) -> float | None:
    return sum((p - o) ** 2 for p, o, *_ in pairs) / len(pairs) if pairs else None


def calibration_svg(pairs, waiting: list[float]) -> str:
    """A reliability diagram: predicted probability against the share that held, in five bins, with the diagonal
    of perfect calibration; predictions still waiting are small dots under the axis. Attributes only (no inline style),
    so the page's content security policy holds."""
    w, h, m = 360, 300, 44
    pw, ph = w - m - 16, h - m - 30

    def x(p):
        return m + p * pw

    def y(v):
        return 16 + (1 - v) * ph

    grid = "".join(f'<line class="grid" x1="{x(t):.1f}" y1="{y(0):.1f}" x2="{x(t):.1f}" y2="{y(1):.1f}"/>'
                   f'<line class="grid" x1="{x(0):.1f}" y1="{y(t):.1f}" x2="{x(1):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="tick" x="{x(t):.1f}" y="{y(0) + 16:.1f}" text-anchor="middle">{t:.1f}</text>'
                   f'<text class="tick" x="{x(0) - 8:.1f}" y="{y(t) + 4:.1f}" text-anchor="end">{t:.1f}</text>'
                   for t in (0, 0.2, 0.4, 0.6, 0.8, 1.0))
    diag = f'<line class="diag" x1="{x(0):.1f}" y1="{y(0):.1f}" x2="{x(1):.1f}" y2="{y(1):.1f}"/>'
    bins = []
    for i in range(5):
        lo, hi = i / 5, (i + 1) / 5
        inside = [(p, o) for p, o, *_ in pairs if lo <= p < hi or (i == 4 and p == 1.0)]
        if inside:
            mp = sum(p for p, _ in inside) / len(inside)
            rate = sum(o for _, o in inside) / len(inside)
            bins.append((mp, rate, len(inside)))
    dots = "".join(
        f'<g class="dot"><circle cx="{x(mp):.1f}" cy="{y(r):.1f}" r="{5 + min(n, 10):.0f}"/>'
        f'<title>Predicted {mp:.2f} on average, {r:.2f} held ({n} prediction{"s" if n != 1 else ""})</title></g>'
        for mp, r, n in bins)
    stacked, seen = [], {}
    for p in sorted(waiting):
        k = round(p, 2)
        stacked.append((p, seen.get(k, 0)))
        seen[k] = seen.get(k, 0) + 1
    ticks = "".join(f'<circle class="wait" cx="{x(p):.1f}" cy="{y(0) + 24 + 7 * i:.1f}" r="3"><title>Waiting: p {p:.2f}</title></circle>'
                    for p, i in stacked)
    h += 7 * max(seen.values(), default=1)
    return f"""<svg class="calib" viewBox="0 0 {w} {h + 10}" role="img" aria-labelledby="calib-t calib-d">
<title id="calib-t">Predicted probability against the share that held</title>
<desc id="calib-d">{len(pairs)} predictions with outcomes in {len(bins)} bins; {len(waiting)} waiting. The diagonal is perfect calibration.</desc>
{grid}{diag}{dots}{ticks}
<text class="axis" x="{x(0.5):.1f}" y="{h + 4}" text-anchor="middle">predicted probability it holds here</text>
<text class="axis" transform="translate(12 {y(0.5):.1f}) rotate(-90)" text-anchor="middle">share that held</text>
</svg>"""


def render_predictions(site: Site) -> str:
    pairs = calibration_pairs(site)
    waiting, unscored = [], []  # (claim, assessment): one row per assessment
    for c in sort_claims(site.claims):
        for a in c.assessments(site.system):
            if a.get("status") == "predicted" and a.get("prediction"):
                waiting.append((c, a))
            elif a.get("status") in ("replicated", "did-not-transfer") and not (a.get("prediction") or {}).get("before_outcome"):
                unscored.append((c, a))

    def cfg(a):
        label = site.config_label(a)
        return f' <span class="muted small">on {e(label)}</span>' if label else ""
    b = brier(pairs)
    if pairs:
        summary = (f"<p><strong>{len(pairs)}</strong> predictions written before their outcome now have one. "
                   f"Brier score <strong class='mono'>{b:.3f}</strong> (0 is perfect; always saying 0.5 scores 0.250).</p>")
    else:
        summary = ("<p>No prediction has an outcome yet, so there is nothing to score. The chart fills in as trials "
                   "report: each dot is a group of predictions, placed at their average probability and at the share "
                   "that held. The small dots under the axis are predictions still waiting. A claim tried on two configurations "
                   "counts twice.</p>")
    rows = "".join(
        f'<tr><td><a href="claims/{e(c.name)}.html">{e(truncate(c.doc["metadata"].get("description", c.name), 90))}</a>'
        f'{cfg(a)}</td><td>{meter(p)}</td><td>{status_badge(a["status"])}</td></tr>' for p, _, c, a in pairs)
    wait_rows = "".join(
        f'<tr><td><a href="claims/{e(c.name)}.html">{e(truncate(c.doc["metadata"].get("description", c.name), 90))}</a>{cfg(a)}</td>'
        f'<td>{meter(a["prediction"]["p_transfer"])}</td></tr>'
        for c, a in sorted(waiting, key=lambda ca: -ca[1]["prediction"]["p_transfer"]))
    unscored_items = "".join(f"<li>{status_badge(a['status'])} <a href='claims/{e(c.name)}.html'>{e(truncate(c.doc['metadata'].get('description', c.name), 110))}</a>{cfg(a)}</li>" for c, a in unscored)
    svg = calibration_svg(pairs, [a["prediction"]["p_transfer"] for _, a in waiting])
    body = f"""
<section class="hero small-hero">
  <p class="eyebrow">Scoring the agent</p>
  <h1>Predictions against outcomes</h1>
  <p class="lede">Before a claim is tried, the agent writes the probability that its finding holds on this system. When the trial reports, the prediction is scored. Over time this shows which kinds of claims carry over, and how far to trust the agent's guesses.</p>
</section>
<div class="cols">
  <section class="panel" aria-labelledby="cal-h"><h2 id="cal-h">Calibration</h2>{summary}{svg}</section>
  <section class="panel" aria-labelledby="w-h"><h2 id="w-h">Waiting for a trial ({len(waiting)})</h2>
  <table class="tbl"><thead><tr><th scope="col">Claim</th><th scope="col">Prediction</th></tr></thead><tbody>{wait_rows or "<tr><td colspan=2 class='muted'>None.</td></tr>"}</tbody></table>
  <p class="small muted">Who wrote each one is on its page. To argue with one, open the claim and use "Dispute the prediction".</p></section>
</div>
{f'<section class="panel" aria-labelledby="s-h"><h2 id="s-h">Scored</h2><table class="tbl"><thead><tr><th scope="col">Claim</th><th scope="col">Prediction</th><th scope="col">Outcome</th></tr></thead><tbody>{rows}</tbody></table></section>' if pairs else ""}
{f'<section class="panel" aria-labelledby="u-h"><h2 id="u-h">Outcomes that do not count</h2><p>These were tried before anyone wrote a probability, so they say nothing about the agent&#39;s calibration.</p><ul class="plain">{unscored_items}</ul></section>' if unscored else ""}
"""
    return page(site, "Predictions", body, "predictions.html")


# ---------------------------------------------------------------- how it works


def render_how(site: Site) -> str:
    steps = [
        ("Watch", "New papers are read for the roles in the system's map and the open questions in its docs. Nothing else."),
        ("Read", "Each paper is read far enough to find what it measured, on what, and how. How much was read is recorded with every claim."),
        ("Catalogue", "A method becomes an option for a role. Each claimed gain becomes a claim: one measure, the baseline, the effect if the paper states one, the conditions (models, precision, engine, dataset, runs, who measured it), and a verbatim quote that a verifier matches against the source."),
        ("Predict", "The claim's conditions are compared with this system's own. The agent writes the probability that the finding holds here, and why, before anything is tried."),
        ("Test behind the judge", "The cheapest informative trial goes first. An implementer turns the method into a change, and Morphogen's judge decides on cases the implementer never saw. A paper's number never decides anything."),
        ("Score the prediction", "The outcome is recorded against the claim: replicated, did not transfer, or not testable here. Predictions written before the outcome are scored, which calibrates the next ones."),
    ]
    ol = "".join(f'<li><span class="step-n mono">{i:02d}</span><div><h3>{e(t)}</h3><p>{e(d)}</p></div></li>'
                 for i, (t, d) in enumerate(steps, 1))
    def label_note(k):
        return f' <span class="muted small">(label {e(", ".join(site.labels[k]))})</span>' if site.labels.get(k) else ""

    labs = "".join(f"<li><span class='mono tag'>research-action: {e(k)}</span> {e(t)}{label_note(k)}</li>"
                   for k, t in (
        ("prioritise", "test this claim sooner; it counts double in the queue"), ("reject", "drop it from the queue"),
        ("dispute", "the transfer prediction is wrong; the next session reassesses it"),
        ("question", "a question to watch"), ("propose-role", "a role to read papers for"),
        ("propose-option", "an option or paper for a role")))
    statuses = "".join(f"<li>{status_badge(s)} {e(STATUS_HELP[s])}</li>" for s in STATUSES + [OBSERVATION])
    body = f"""
<section class="hero small-hero">
  <p class="eyebrow">How it works</p>
  <h1>A research loop with a judge at the end</h1>
  <p class="lede">Papers report far more gains than anyone tests, mostly once, on setups unlike yours. The research agent keeps a catalog of those claims for this system and tests the promising ones, so that only measured gains reach the code.</p>
</section>
<ol class="loop">{ol}</ol>
<div class="cols">
<section class="panel" aria-labelledby="st-h"><h2 id="st-h">What a status means</h2><ul class="plain statuses">{statuses}</ul>
<p class="small">"Replicated" means the finding held on this system's setup. It is a transfer test of the method, not a reproduction of the paper, and "did not transfer" is not a refutation of it.</p></section>
<section class="panel" aria-labelledby="sg-h"><h2 id="sg-h">Steering it</h2>
<p>The agent takes direction from GitHub issues. The buttons on this site open one, filled in, for you to edit and submit; nothing is sent until you do. Each ends with a <span class="mono">research-action:</span> line, which the agent reads first:</p>
<ul class="plain">{labs}</ul>
<p class="small muted">GitHub applies labels from a link only for people who can triage the repository, which is why the body line comes first. The agent records every issue but acts only on those from the repository's owner, members and collaborators.</p></section>
</div>
<section class="panel" aria-labelledby="f-h"><h2 id="f-h">Files, not a service</h2>
<p>Every claim is a YAML file in the repository ({link(site.file_url("schemas/evidence-claim.v1.json"), "schemas/evidence-claim.v1.json")}), and the roles and options are Backstage entity files. This site is built from them by <span class="mono">site/build.py</span>; <a href="data/claims.json">data/claims.json</a> holds the same records for other tools. The judge never reads the claims: what decides a change is only what it measures.</p></section>
"""
    return page(site, "How it works", body, "how.html")


# ---------------------------------------------------------------- the agent's own files


def load_research(d: Path | None) -> dict:
    """queue.json, watch.yaml, seen.jsonl and index.json from the research agent's directory (morphogen.research;
    demos/research-loop/README.md, "Files a website reads"). Each is optional."""
    out: dict = {}
    if d is None or not d.is_dir():
        return out
    for name, key in (("queue.json", "queue"), ("index.json", "index")):
        if (d / name).is_file():
            out[key] = json.loads((d / name).read_text(encoding="utf-8"))
    if (d / "watch.yaml").is_file():
        out["watch"] = yaml.safe_load((d / "watch.yaml").read_text(encoding="utf-8")) or {}
    if (d / "seen.jsonl").is_file():
        out["seen"] = [json.loads(line) for line in (d / "seen.jsonl").read_text(encoding="utf-8").splitlines()
                       if line.strip()]
    return out


def check_index(site: Site) -> list[str]:
    """Where index.json and the claim files disagree (the agent rewrites the index from the files, so they should not)."""
    index = site.research.get("index")
    if not index:
        return []
    listed = {c.get("name") for c in index.get("claims") or []}
    found = {c.name for c in site.claims}
    return ([f"index.json lists {n}, which no claim file holds" for n in sorted(listed - found)]
            + [f"{n} is not in index.json" for n in sorted(found - listed)])


def render_queue(site: Site) -> str:
    q = site.research.get("queue") or {}
    items = site.queue()
    by_name = site.by_name()
    cards = []
    for i, it in enumerate(items, 1):
        name = it.get("claim", "")
        c = by_name.get(name)
        title = c.doc["metadata"].get("description", name) if c else name
        head = (f'<a href="claims/{e(name)}.html">{e(title)}</a>' if c else e(title))
        steer = []
        for key, text in (("prioritised_by", "prioritised"), ("rejected_by", "rejected"), ("disputed_by", "disputed")):
            who = it.get(key) or []
            if who:
                steer.append(f'<span class="tag">{e(text)} by {e(", ".join(str(w) for w in who))}</span>')
        score = it.get("score")
        nums = [("score", f"{score:.3f}" if isinstance(score, (int, float)) else "none"),
                ("bits", it.get("information_bits")), ("hours", it.get("cost_hours"))]
        num_html = "".join(f'<span class="qnum"><span class="f-lab">{e(k)}</span> <span class="mono">{e(v)}</span></span>'
                           for k, v in nums if v is not None)
        p = it.get("p_transfer")
        acts = ""
        if c is not None:
            pri = site.issue("prioritise", f"Prioritise: {name}", issue_body("prioritise", site, c, [
                "Please test this claim sooner.", "", "Why it is worth a trial now:", ""]))
            rej = site.issue("reject", f"Reject: {name}", issue_body("reject", site, c, [
                "Please drop this claim from the queue.", "", "Why:", ""]))
            acts = (f'<p class="actions"><a class="btn ghost small-btn" href="{e(pri)}" rel="noopener noreferrer">Test sooner</a>'
                    f' <a class="btn ghost small-btn" href="{e(rej)}" rel="noopener noreferrer">Reject</a></p>')
        cards.append(f"""<li class="qitem"><span class="qrank mono" aria-label="Rank {i}">{i:02d}</span><article class="card">
<div class="card-top"><span class="mono muted small">{e(ref_name(it.get("role")))} · option {e(ref_name(it.get("about")))}</span>{meter(p) if isinstance(p, (int, float)) else ""}</div>
<h3>{head}</h3>
<p class="qnums">{num_html}{"".join(steer)}</p>
{f'<p><span class="f-lab">Plan</span><br>{e(it["plan"])}</p>' if it.get("plan") else ""}
{f'<details><summary>Why this probability</summary><p class="small">{e(it["reason"])}</p></details>' if it.get("reason") else ""}
{acts}</article></li>""")
    how = q.get("how", "")
    when = f" Ranked on {e(q['date'])}." if q.get("date") else ""
    listing = (f'<ol class="queue">{"".join(cards)}</ol>' if cards else
               '<p class="panel muted">No queue yet: the research agent writes one (research/queue.json) when it ranks its claims.</p>')
    body = f"""
<section class="hero small-hero">
  <p class="eyebrow">The research agent's queue</p>
  <h1>Next to test</h1>
  <p class="lede">Claims ranked by what a trial would teach for its cost: a prediction near 0.5 teaches the most, a cheap trial costs the least.{when}</p>
  {f'<p class="small muted">{e(how)}</p>' if how else ""}
</section>
{listing}
"""
    return page(site, "Next to test", body, "queue.html")


def watch_html(site: Site) -> str:
    """What the agent watches (watch.yaml) and what became of the papers it saw (seen.jsonl)."""
    w = site.research.get("watch") or {}
    seen = site.research.get("seen") or []
    if not w and not seen:
        return ""
    topics = []
    for t in w.get("topics") or []:
        roles = " ".join(f'<a class="mono" href="#{e(r)}">{e(r)}</a>' for r in t.get("roles") or [])
        terms = " ".join(f'<span class="tag">{e(x)}</span>' for x in t.get("terms") or []) or \
            '<span class="muted small">terms still to be filled in by the next session</span>'
        cats = ", ".join(str(x) for x in t.get("categories") or [])
        topics.append(f"""<li class="opt"><h4 class="mono">{e(t.get("name", ""))}</h4><p>{e(t.get("question", ""))}</p>
<p class="small">{roles}{f' <span class="muted">· {e(cats)}</span>' if cats else ""}</p><p class="terms">{terms}</p></li>""")
    counts: dict = {}
    for paper in seen:
        counts[paper.get("status", "")] = counts.get(paper.get("status", ""), 0) + 1
    count_html = ", ".join(f"{n} {e(k)}" for k, n in sorted(counts.items(), key=lambda x: -x[1]))
    cataloged = [x for x in seen if x.get("status") == "cataloged"]
    cat_html = "".join(
        f'<li>{link("https://arxiv.org/abs/" + str(x.get("id", "")), x.get("title", ""))} <span class="mono muted small">{e(x.get("id", ""))}</span></li>'
        for x in cataloged)
    return f"""<section class="panel" id="watching" aria-labelledby="w-h"><h2 id="w-h">Watching</h2>
{f'<p>{e(w["conditions"])}</p>' if w.get("conditions") else ""}
{f'<ul class="opts">{"".join(topics)}</ul>' if topics else ""}
{f'<p class="small"><span class="f-lab">Papers seen</span> {len(seen)}: {count_html}.</p>' if seen else ""}
{f'<details><summary>{len(cataloged)} papers catalogued</summary><ul class="plain">{cat_html}</ul></details>' if cataloged else ""}
</section>"""


# ---------------------------------------------------------------- build


def build(config_path: Path, out: Path, root: Path = ROOT) -> Site:
    with config_path.open("rb") as f:
        cfg = tomllib.load(f)
    srcs = cfg.get("sources", {})
    schema_path = srcs.get("schema")
    schema = json.loads((root / schema_path).read_text(encoding="utf-8")) if schema_path else None
    claims = load_claims([root / d for d in srcs.get("claims", [])], root.resolve(), schema)
    docs = []
    for p in srcs.get("catalog", []):
        if (root / p).is_file():
            docs += load_yaml_docs(root / p)
        else:
            print(f"build: {p} does not exist; skipped", file=sys.stderr)
    research = load_research(root / srcs["research"] if srcs.get("research") else None)
    site = Site(cfg.get("title", "Morphogen research"), cfg["repo"], cfg.get("branch", "main"), cfg["system"],
                cfg.get("labels", {}), claims, Catalog(docs), research)
    for problem in check_index(site):
        print(f"build: {problem}", file=sys.stderr)

    if out.exists():
        shutil.rmtree(out)
    (out / "claims").mkdir(parents=True)
    (out / "data").mkdir()
    shutil.copytree(HERE / "static", out / "assets")
    write = lambda rel, text: (out / rel).write_text(text, encoding="utf-8")  # noqa: E731
    write("index.html", render_index(site))
    write("roles.html", render_roles(site))
    write("queue.html", render_queue(site))
    write("predictions.html", render_predictions(site))
    write("how.html", render_how(site))
    for c in claims:
        write(f"claims/{c.name}.html", render_claim(site, c))
    data = [{"name": c.name, "path": c.path, "status": c.status(site.system), "statuses": c.statuses(site.system),
             "date": c.date(),
             "record": _jsonable(c.doc)} for c in sort_claims(claims)]
    write("data/claims.json", json.dumps({"system": site.system, "claims": data}, indent=1, ensure_ascii=False))
    write(".nojekyll", "")
    return site


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--config", type=Path, default=HERE / "config.toml")
    ap.add_argument("--out", type=Path, default=HERE / "_build")
    ap.add_argument("--root", type=Path, default=ROOT, help="the repository the config's paths are relative to")
    args = ap.parse_args(argv)
    site = build(args.config, args.out, root=args.root.resolve())
    print(f"build: {len(site.claims)} claims, {len(site.catalog.roles)} roles, {len(site.catalog.options)} options -> {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
