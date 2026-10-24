"""Prometheus text exposition -> window means -> observations. Pure functions; no database.

At each window boundary the observer scrapes every target. For a configured histogram, a window's value
is (sum at its end - sum at its start) / (count at its end - count at its start), over the series not
excluded by label: the mean of the requests the target finished inside the window. A window with no
new requests, or in which a counter went down (the target restarted), gives no observation.

  <target's subject>  sosa:hasSimpleResult <mean>  {sosa:observedProperty: <property>}
                      valid from the window's start to its end, evidence observed,
                      referenced by the scraped URL and the window
"""
from __future__ import annotations

import math
import re
import urllib.parse
from datetime import datetime, timezone

SOSA = "http://www.w3.org/ns/sosa/"
XSD = "http://www.w3.org/2001/XMLSchema#"
LINE = re.compile(r'^([a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(.*)\})?\s+(\S+)(?:\s+\S+)?$')
LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\]|\\.)*)"')


def parse(text: str) -> list[tuple[str, dict, float]]:
    """(metric name, labels, value) for each sample line; comments and malformed lines are skipped."""
    out = []
    for line in text.splitlines():
        m = LINE.match(line.strip())
        if not m or line.startswith("#"):
            continue
        try:
            v = float(m.group(3))
        except ValueError:
            continue
        labels = {k: bytes(x, "utf-8").decode("unicode_escape") for k, x in LABEL.findall(m.group(2) or "")}
        out.append((m.group(1), labels, v))
    return out


def totals(text: str, config: dict) -> dict[str, tuple[float, float]]:
    """histogram name -> (sum, count) over its series not excluded, from one scrape."""
    samples = parse(text)
    out = {}
    for h in config["metrics"]:
        name, exclude = h["histogram"], h.get("exclude") or {}
        keep = lambda labels: not any(labels.get(k) in v for k, v in exclude.items())
        s = sum(v for n, labels, v in samples if n == name + "_sum" and keep(labels))
        c = sum(v for n, labels, v in samples if n == name + "_count" and keep(labels))
        if any(n in (name + "_sum", name + "_count") for n, _, _ in samples):
            out[name] = (s, c)
    return out


def ops(subject: str, url: str, before: dict, after: dict, start: float, end: float, config: dict) -> list[dict]:
    """The window's observations for one target, from its totals at the start and the end."""
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
    out = []
    for h in config["metrics"]:
        name = h["histogram"]
        if name not in before or name not in after:
            continue
        ds, dc = after[name][0] - before[name][0], after[name][1] - before[name][1]
        if dc <= 0 or ds < 0:                       # nothing finished, or the counters were reset
            continue
        mean = ds / dc
        if math.isnan(mean) or math.isinf(mean):
            continue
        ref = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(
            {"metric": name, "from": f"{start:.0f}", "to": f"{end:.0f}"})
        out.append({"op": "add_claim", "subject": subject, "predicate": SOSA + "hasSimpleResult",
                    "object": {"value": {"@value": round(mean, 4), "@type": XSD + "decimal"}},
                    "qualifiers": {SOSA + "observedProperty": h["property"]},
                    "valid_from": iso(start), "valid_to": iso(end), "evidence_type": "observed",
                    "references": [{"source_uri": ref}]})
    return out
