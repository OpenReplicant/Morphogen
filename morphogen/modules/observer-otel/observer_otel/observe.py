"""OTLP metrics -> one change set of observations per window. Pure functions; no database.

A request (OTLP JSON, or protobuf converted to the same shape) gives points: per resource, metric and
data point, the time, count and sum (a histogram) or one value (a gauge). For each resource and mapped
metric with points in the window [start, end):

  <subject from the resource>  sosa:hasSimpleResult <sum / count>   {sosa:observedProperty: <property>}
                               valid from the window's start to its end, evidence observed,
                               referenced by the receiver URL naming the resource, metric and window

The value is the metric's mean over the window, so a 1-second export interval and a 60-second window
give the same answer as one export per window.
"""
from __future__ import annotations

import math
import re
import urllib.parse
from datetime import datetime, timezone

SOSA = "http://www.w3.org/ns/sosa/"
XSD = "http://www.w3.org/2001/XMLSchema#"


def window(now: float, seconds: float) -> tuple[float, float]:
    """The last complete window before `now`, aligned to multiples of `seconds`."""
    end = math.floor(now / seconds) * seconds
    return end - seconds, end


def _attrs(resource: dict) -> dict:
    out = {}
    for a in resource.get("attributes", []):
        v = a.get("value", {})
        out[a.get("key")] = next((v[k] for k in ("stringValue", "intValue", "doubleValue", "boolValue") if k in v), None)
    return out


def _number(p: dict):
    for k in ("asDouble", "asInt"):
        if k in p:
            return float(p[k])
    return None


def points(body: dict) -> list[dict]:
    """[{attrs, metric, t (seconds), count, sum}] from one OTLP ExportMetricsServiceRequest."""
    out = []
    for rm in body.get("resourceMetrics", []):
        attrs = _attrs(rm.get("resource", {}))
        for sm in rm.get("scopeMetrics", []):
            for m in sm.get("metrics", []):
                if "histogram" in m:
                    for p in m["histogram"].get("dataPoints", []):
                        n = int(p.get("count", 0))
                        if n > 0 and p.get("sum") is not None:
                            out.append({"attrs": attrs, "metric": m["name"], "t": int(p["timeUnixNano"]) / 1e9,
                                        "count": n, "sum": float(p["sum"])})
                elif "gauge" in m:
                    for p in m["gauge"].get("dataPoints", []):
                        v = _number(p)
                        if v is not None:
                            out.append({"attrs": attrs, "metric": m["name"], "t": int(p["timeUnixNano"]) / 1e9,
                                        "count": 1, "sum": v})
    return out


def subject(template: str, attrs: dict):
    """`template` with each {attribute} replaced by the resource's value; None when one is missing."""
    missing = False

    def value(m):
        nonlocal missing
        v = attrs.get(m.group(1))
        if v is None or not str(v).strip():
            missing = True
            return ""
        return urllib.parse.quote(str(v), safe="-._~")
    out = re.sub(r"\{([^{}]+)\}", value, template)
    return None if missing else out


def ops(pts: list[dict], start: float, end: float, config: dict, source: str) -> list[dict]:
    """One observation per (subject, property) with points in [start, end)."""
    iso = lambda t: datetime.fromtimestamp(t, timezone.utc).isoformat()
    props = {m["metric"]: m["property"] for m in config["metrics"]}
    acc: dict[tuple[str, str, str], list[float]] = {}
    for p in pts:
        if not start <= p["t"] < end or p["metric"] not in props:
            continue
        s = subject(config["subject"], p["attrs"])
        if not s:
            continue
        a = acc.setdefault((s, p["metric"], props[p["metric"]]), [0, 0.0])
        a[0] += p["count"]
        a[1] += p["sum"]
    out = []
    for (s, metric, prop), (n, total) in sorted(acc.items()):
        mean = total / n
        if math.isnan(mean) or math.isinf(mean):
            continue
        ref = source + "?" + urllib.parse.urlencode({"resource": s, "metric": metric, "from": f"{start:.0f}", "to": f"{end:.0f}"})
        out.append({"op": "add_claim", "subject": s, "predicate": SOSA + "hasSimpleResult",
                    "object": {"value": {"@value": round(mean, 4), "@type": XSD + "decimal"}},
                    "qualifiers": {SOSA + "observedProperty": prop},
                    "valid_from": iso(start), "valid_to": iso(end), "evidence_type": "observed",
                    "references": [{"source_uri": ref}]})
    return out
