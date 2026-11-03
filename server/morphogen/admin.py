"""Admin pages: a menu of the tools filling the admin-ui slots, and a read-only report.

Both are static HTML written into the data directory (`admin/index.html` and
`admin/report.html`). They read the lists, the evidence log and the archive and
change nothing. They open as files, inside a web desktop such as Puter, or
through `morphogen-admin --serve`, a read-only file server on localhost that
runs as its own process, never inside the judge.

The menu lists what fills each slot of the `admin-ui` system. A component counts
as installed when its status starts with "in use" and it has a `url`; links open
in new tabs. Tools in the catalog's `admin_ui` section are listed as available,
not installed: Morphogen never installs them.

Everything shown comes from entries the agent can write, so all text is escaped
and only http, https and relative links are kept. No page accepts input:
approvals stay in the conversation and in pull requests.
"""

from __future__ import annotations

import argparse
import datetime
import functools
import html
import http.server
import json
from pathlib import Path
from urllib.parse import urlparse


from . import strategies as strategies_mod
from . import documents
from .config import data_dir, load_config, project_root
from .project import SAMPLES, stores

ADMIN_SYSTEM = "admin-ui"

STYLE = """
:root { --bg: #fbfbfa; --fg: #1d1d1b; --muted: #6b6b66; --line: #e2e1dc; --accent: #2f5f8f;
        --pass: #2e7d4f; --fail: #a33a2b; }
@media (prefers-color-scheme: dark) {
  :root { --bg: #18181a; --fg: #ebebe6; --muted: #9a9a94; --line: #34343a; --accent: #8db4dc;
          --pass: #6fbf8c; --fail: #e08572; } }
body { background: var(--bg); color: var(--fg); font: 15px/1.5 system-ui, sans-serif;
       margin: 0 auto; max-width: 960px; padding: 24px 16px; }
h1 { font-size: 22px; margin: 0 0 4px; } h2 { font-size: 17px; margin: 28px 0 8px; }
.muted { color: var(--muted); } a { color: var(--accent); }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { color: var(--muted); font-weight: 600; }
code { font-size: 13px; } .pass { color: var(--pass); } .fail { color: var(--fail); }
.wrap { overflow-x: auto; } ul.tree { margin: 0; padding-left: 18px; }
"""


def _e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def safe_url(url) -> str | None:
    """http, https or a relative path; anything else (javascript:, data:, file:) is dropped."""
    if not isinstance(url, str) or not url.strip():
        return None
    url = url.strip()
    scheme = urlparse(url).scheme.lower()
    if scheme in ("http", "https"):
        return url
    if scheme == "" and not url.startswith("//") and ":" not in url.split("/", 1)[0]:
        return url
    return None


def _link(url, text) -> str:
    u = safe_url(url)
    if not u:
        return _e(text)
    return f'<a href="{_e(u)}" target="_blank" rel="noopener noreferrer">{_e(text)}</a>'


def _page(title: str, body: str, generated: str) -> str:
    return (f"<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
            f"<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">"
            f"<title>{_e(title)}</title><style>{STYLE}</style></head><body>{body}"
            f"<p class=\"muted\">Generated {_e(generated)}. Read-only: nothing on this page changes "
            f"Morphogen.</p></body></html>")


def _catalog(root: Path) -> dict:
    f = root / "catalogs.yaml"
    if not f.exists():
        f = SAMPLES / "catalogs.yaml"
    try:
        return documents.load("catalogs", f)
    except documents.DocumentError:
        return {}


def installed(component: dict | None) -> bool:
    return bool(component) and str(component.get("status", "")).startswith("in use") \
        and safe_url(component.get("url")) is not None


def menu_html(lists, catalog: dict, generated: str) -> str:
    system = lists.get("systems", ADMIN_SYSTEM)
    rows = []
    for slot_id in (system or {}).get("slots", []):
        slot = lists.get("slots", slot_id) or {"id": slot_id}
        comp = lists.get("components", slot["filled_by"]) if slot.get("filled_by") else None
        if installed(comp) and comp["url"] == "index.html":
            tool = '<span class="muted">this page</span>'
        elif installed(comp):
            tool = _link(comp["url"], comp.get("name") or comp["id"])
        elif comp:
            tool = f'{_e(comp.get("name") or comp["id"])} <span class="muted">(not installed)</span>'
        else:
            tool = '<span class="muted">empty</span>'
        rows.append(f"<tr><td><code>{_e(slot_id.split('/', 1)[-1])}</code></td>"
                    f"<td>{_e(slot.get('interface', ''))}</td><td>{tool}</td></tr>")
    available = []
    for entry in catalog.get("admin_ui") or []:
        slot = str(entry.get("slot", "")).split("/", 1)[-1]
        available.append(f"<tr><td>{_link(entry.get('url'), entry.get('name'))}</td><td><code>{_e(slot)}</code></td>"
                         f"<td>{_e(entry.get('finds', ''))}<br><span class=\"muted\">Licence: "
                         f"{_e(entry.get('licence', 'unknown'))}. Trust: {_e(entry.get('trust', 'unvetted'))}."
                         f"</span></td></tr>")
    if not system:
        intro = (f"<p>No <code>{ADMIN_SYSTEM}</code> system in the lists yet. "
                 "<code>init_project</code> seeds one in a new project.</p>")
    else:
        intro = ("<p class=\"muted\">What fills each slot of the admin UI. A tool you run yourself appears "
                 "here once its component has <code>status: in use</code> and a <code>url</code>.</p>")
    body = (f"<h1>Morphogen</h1>{intro}<div class=\"wrap\"><table><tr><th>Slot</th><th>Role</th>"
            f"<th>Tool</th></tr>{''.join(rows)}</table></div>")
    if available:
        body += ("<h2>In the catalog</h2><p class=\"muted\">Not installed by Morphogen. Pin, check the licence "
                 "and advisories, and read it before running one.</p><div class=\"wrap\"><table><tr>"
                 "<th>Tool</th><th>Slot</th><th>What</th></tr>"
                 f"{''.join(available)}</table></div>")
    return _page("Morphogen", body, generated)


def _short(sha) -> str:
    return str(sha or "")[:10]


def _lineage(variants: list[dict]) -> str:
    """Candidates nested under the commit they were built on."""
    by_base: dict[str, list[dict]] = {}
    for v in variants:
        by_base.setdefault(v["base"], []).append(v)
    candidates = {v["candidate"] for v in variants}
    roots = [b for b in by_base if b not in candidates]

    def node(sha: str, seen: set) -> str:
        items = []
        for v in by_base.get(sha, []):
            if v["candidate"] in seen:
                continue
            gain = f"{v['gain']:+.1%}" if isinstance(v.get("gain"), (int, float)) else "—"
            label = (f'<span class="{_e(v["verdict"])}">{_e(v["verdict"])}</span> '
                     f'<code>{_e(_short(v["candidate"]))}</code> {_e(v["strategy"])}'
                     f'{" / " + _e(v["approach"]) if v.get("approach") else ""} {_e(gain)}')
            items.append(f"<li>{label}{node(v['candidate'], seen | {v['candidate']})}</li>")
        return f"<ul class=\"tree\">{''.join(items)}</ul>" if items else ""

    return "".join(f"<li><code>{_e(_short(r))}</code>{node(r, {r})}</li>" for r in roots)


def report_html(lists, evidence, generated: str, recent: int = 30) -> str:
    ok, bad = evidence.verify()
    records = evidence.dump()
    chain = '<span class="pass">intact</span>' if ok else f'<span class="fail">broken at record {_e(bad)}</span>'
    parts = ["<h1>Morphogen report</h1>", f"<p>Evidence: {len(records)} records, chain {chain}.</p>"]

    parts.append("<h2>Map</h2>")
    for system in lists.query("systems"):
        rows = []
        for slot_id in system.get("slots", []):
            slot = lists.get("slots", slot_id) or {}
            comp = lists.get("components", slot.get("filled_by")) if slot.get("filled_by") else None
            filler = _e(slot.get("filled_by") or "empty")
            if comp and comp.get("system"):
                filler += f' <span class="muted">→ system <code>{_e(comp["system"])}</code></span>'
            rows.append(f"<tr><td><code>{_e(slot_id)}</code></td><td>{_e(', '.join(slot.get('accepts', [])))}</td>"
                        f"<td>{filler}</td><td>{_e(slot.get('interface', ''))}</td></tr>")
        parts.append(f"<h3><code>{_e(system['id'])}</code> <span class=\"muted\">{_e(system.get('interface', ''))}"
                     f"</span></h3><p class=\"muted\">{_e(system.get('description', ''))}</p>"
                     "<div class=\"wrap\"><table><tr><th>Slot</th><th>Accepts</th><th>Filled by</th>"
                     f"<th>Interface</th></tr>{''.join(rows)}</table></div>")

    st = lists.status() if hasattr(lists, "status") else {"mounted": [], "dangling": []}
    if st["mounted"] or st["dangling"]:
        rows = "".join(
            f"<tr><td><code>{_e(m['name'])}</code></td><td>{_e(m['source'])}</td>"
            f"<td>{_e(('pinned at ' + str(m['commit'])[:10]) if m['pinned'] else 'unpinned (read live)')}</td>"
            f"<td>{_e(m['entries'])}</td><td>{_e(m['error'] or '')}</td></tr>" for m in st["mounted"])
        parts.append("<h2>Mounted maps</h2><p class=\"muted\">Read-only here. Their entries are another map's "
                     "claims (trust: stated).</p><div class=\"wrap\"><table><tr><th>Map</th><th>Source</th>"
                     f"<th>Version</th><th>Entries</th><th>Error</th></tr>{rows}</table></div>")
        if st["dangling"]:
            rows = "".join(f"<tr><td><code>{_e(d['map'])}</code></td><td><code>{_e(d['id'])}</code></td>"
                           f"<td>{_e(d['field'])} → <code>{_e(d['ref'])}</code></td><td>{_e(d['why'])}</td></tr>"
                           for d in st["dangling"])
            parts.append("<h3>References that do not resolve</h3><div class=\"wrap\"><table><tr><th>Map</th>"
                         f"<th>Entry</th><th>Reference</th><th>Why</th></tr>{rows}</table></div>")

    targets = sorted({(r.get("subject") or {}).get("path") for r in records
                      if r.get("by") == "judge" and r.get("kind") == "verdict"} - {None})
    parts.append("<h2>Archive</h2>")
    if not targets:
        parts.append("<p class=\"muted\">No verdicts yet.</p>")
    for target in targets:
        variants = strategies_mod.archive(evidence, target)
        payoff = strategies_mod.payoff(variants)
        rows = "".join(f"<tr><td>{_e(s)}</td><td>{_e(t['trials'])}</td><td>{_e(t['passes'])}</td>"
                       f"<td>{_e(t['gain_per_trial'])}</td></tr>" for s, t in payoff.items())
        parts.append(f"<h3><code>{_e(target)}</code></h3><ul class=\"tree\">{_lineage(variants)}</ul>"
                     "<div class=\"wrap\"><table><tr><th>Strategy</th><th>Trials</th><th>Passes</th>"
                     f"<th>Gain per trial</th></tr>{rows}</table></div>")

    rows = []
    for r in reversed(records[-recent:]):
        rows.append(f"<tr><td>{_e(r.get('seq'))}</td><td>{_e(str(r.get('at', ''))[:19])}</td>"
                    f"<td>{_e(r.get('trust'))}</td><td>{_e(r.get('by'))}</td><td>{_e(r.get('claim'))}</td></tr>")
    parts.append("<h2>Recent evidence</h2>" + (
        "<div class=\"wrap\"><table><tr><th>#</th><th>At</th><th>Trust</th><th>By</th><th>Claim</th></tr>"
        f"{''.join(rows)}</table></div>" if rows else "<p class=\"muted\">No evidence yet.</p>"))
    return _page("Morphogen report", "".join(parts), generated)


def write(root: Path, cfg: dict, out: Path | None = None) -> dict:
    out = out or data_dir(root, cfg) / "admin"
    out.mkdir(parents=True, exist_ok=True)
    lists, evidence = stores(root, cfg)
    generated = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    (out / "index.html").write_text(menu_html(lists, _catalog(root), generated))
    (out / "report.html").write_text(report_html(lists, evidence, generated))
    return {"menu": str(out / "index.html"), "report": str(out / "report.html")}


class _ReadOnly(http.server.SimpleHTTPRequestHandler):
    """Static files only: GET and HEAD. Anything else gets 501 Not Implemented."""

    def log_message(self, format, *args):  # quiet; the operator sees the URL once
        pass


def make_server(directory: Path, port: int, host: str = "127.0.0.1") -> http.server.ThreadingHTTPServer:
    handler = functools.partial(_ReadOnly, directory=str(directory))
    return http.server.ThreadingHTTPServer((host, port), handler)


def serve(directory: Path, port: int, host: str = "127.0.0.1") -> None:
    """Serve the pages read-only, on localhost unless told otherwise."""
    with make_server(directory, port, host) as httpd:
        print(json.dumps({"serving": f"http://{host}:{httpd.server_address[1]}/", "directory": str(directory)}),
              flush=True)
        httpd.serve_forever()


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="morphogen-admin", description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", type=Path, help="project root (default: MORPHOGEN_PROJECT or the current directory)")
    ap.add_argument("--out", type=Path, help="where to write the pages (default: <data_dir>/admin)")
    ap.add_argument("--serve", type=int, metavar="PORT", help="then serve them read-only on localhost")
    args = ap.parse_args(argv)
    root = (args.project or project_root()).resolve()
    paths = write(root, load_config(root), args.out)
    print(json.dumps(paths), flush=True)
    if args.serve:
        serve(Path(paths["menu"]).parent, args.serve)


if __name__ == "__main__":
    main()
