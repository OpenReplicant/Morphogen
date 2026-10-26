"""The ranking test (T37, R5-O18 (9)): does asking the gap finder's questions in order of how many gaps an answer is
expected to close finish a system map in fewer questions than the shapes' fixed order (sh:order, then target)?

A simulated interview over real systems. Each system is a compose file, mapped by encoder-compose; that map is the
truth. The interview starts from what a person says first (the system and its services, by name) and goes on one
question at a time: the real gap finder (gaps-shacl, the kk-tosca shapes) lists what is missing, an interviewer picks
one gap, and the person answers it from the truth, what the question asks and nothing more:

  no-image X        X's image, pinned (catalog lookup pins a tag, T14; a service built from source gets a placeholder)
  unconnected X     every connection X has, either way
  no-limit X        a limit, if nothing calls X; else who calls X (so X is not an entry point)
  no-limit (system) a limit on a service nothing calls, else on the first service
It stops when no gap is left. Interviewers:

  fixed     the gap finder's order
  ranked    the gap whose answer is expected to close the most open gaps; ties in the fixed order. How likely two
            services are to connect comes from the other applications of the corpus, never the one interviewed,
            by the kinds of the services (an image's name, once known)
  random    any open gap (seeded; the spread across seeds)
  ranked-images  the same, but the image questions first, in the fixed order: the measure gives an image question no
            value for what it tells about kinds, so "ranked" asks them last and its prior sees only "other"
  names     a second prior from the services' names (designed after "ranked" gained nothing; reported beside it)
  hindsight the same measure with the answers known: not an interviewer, not a proven optimum
Counted: questions to the end, by kind, and the connections still unknown then (a map with no gap can still lack a
connection between two services that each have another).

What the corpus's connections are: encoder-compose reads depends_on and service URLs, so they are start-order
dependencies, not call graphs; in two of the three large systems most go to one logging or tracing service.

  python3 morphogen/evals/ranking/run.py fetch       the corpus, pinned by commit, into KK_EVAL_CACHE/ranking
  python3 morphogen/evals/ranking/run.py run [--seeds N] [--only NAME] [--json FILE]

Decided before the first run (docs/rebuild-5.md T37): the ranking is kept if, on the systems of 10 or more services,
it asks at least 10% fewer questions than the fixed order in total and leaves no more connections unknown.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
for p in (ROOT / "kernel" / "src", ROOT / "kernel" / "providers" / "gaps-shacl", ROOT / "morphogen" / "modules" / "encoder-compose"):
    sys.path.insert(0, str(p))

from encoder_compose import encode  # noqa: E402
from gaps_shacl import gaps as finder  # noqa: E402

CACHE = Path(os.environ.get("KK_EVAL_CACHE") or Path.home() / ".cache/knowledge-kernel/eval") / "ranking"
CORPUS = [("docker/awesome-compose", "30f4b7f6a6c3b0c0ecf4d4efb0de203c48d11562"),
          ("delimitrou/DeathStarBench", "6ecb09706140f8730b5385c08f1386c654c3c526"),
          ("microservices-demo/microservices-demo", "9dff06fae4981921caec6a62393a6ebfce4b3e3f")]
KKT = "https://w3id.org/knowledge-kernel/tosca#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
MAX = "https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue"
OBSERVED = "http://www.w3.org/ns/sosa/observedProperty"
LATENCY = "urn:kk:property:latency-seconds-mean"
GAP = "urn:kk:gap-kind:"
COMPOSE = re.compile(r"(docker-)?compose[^/]*\.ya?ml")


# ------------------------------------------------------------------ the corpus
def fetch() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for repo, sha in CORPUS:
        d = CACHE / repo.split("/")[1]
        if not d.exists():
            subprocess.run(["git", "init", "-q", str(d)], check=True)
            subprocess.run(["git", "-C", str(d), "fetch", "-q", "--depth", "1", f"https://github.com/{repo}", sha], check=True)
            subprocess.run(["git", "-C", str(d), "checkout", "-q", "FETCH_HEAD"], check=True)
        got = subprocess.run(["git", "-C", str(d), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        if got != sha:
            raise SystemExit(f"{repo}: {got}, expected {sha}")
        print(f"{repo} {sha}")


def truth(text: str, name: str) -> dict:
    """A compose file -> {name, nodes: {iri: {label, image}}, edges: {(caller, callee)}}, services with no connection
    dropped: no answer closes "what does X call" for a service that calls nothing, and both interviewers would ask it
    exactly once."""
    ops = encode.compose("compose.yaml", text, name)
    nodes = {o["subject"]: {"label": "", "image": None} for o in ops if o["predicate"] == KKT + "memberOf"}
    edges = {(o["subject"], o["object"]["entity"]) for o in ops
             if o["predicate"] == KKT + "connectsTo" and o["object"]["entity"] in nodes and o["subject"] != o["object"]["entity"]}
    for o in ops:
        if o["subject"] in nodes and o["predicate"] == LABEL:
            nodes[o["subject"]]["label"] = o["object"]["value"]["@value"]
        if o["subject"] in nodes and (o.get("qualifiers") or {}).get(KKT + "propertyName") == "image":
            nodes[o["subject"]]["image"] = o["object"]["value"]["@value"]
    linked = {n for e in edges for n in e}
    return {"name": name, "nodes": {n: v for n, v in nodes.items() if n in linked}, "edges": edges}


def corpus(cache: Path = CACHE) -> list[dict]:
    """One system per application (the compose file of each directory with the most connections; DeathStarBench's
    variants of one application are one application), each with at least two connected services."""
    best: dict[str, dict] = {}
    for f in sorted(cache.rglob("*")):
        if not COMPOSE.fullmatch(f.name) or {"vendor", "openshift", "lua-bridge-tracer"} & set(f.parts):
            continue
        rel = f.relative_to(cache).parts
        app = "/".join(rel[:2]) if rel[0] != "microservices-demo" else "microservices-demo/sock-shop"
        try:
            t = truth(f.read_text(), re.sub(r"[^a-z0-9-]", "-", app.split("/")[-1].lower()))
        except Exception:            # not a single compose document (OpenShift templates and the like)
            continue
        t["app"], t["file"] = app, "/".join(rel)
        if len(t["nodes"]) >= 2 and (app not in best or len(t["edges"]) > len(best[app]["edges"])):
            best[app] = t
    return sorted(best.values(), key=lambda t: (-len(t["nodes"]), t["app"]))


# ------------------------------------------------------------------ what a service is, as far as the interviewer knows
def kind(image: str | None) -> str | None:
    """An image's name without registry, tag or digest: postgres, memcached, deathstarbench/social-network-microservices."""
    if not image:
        return None
    parts = image.split("@")[0].split("/")
    parts[-1] = parts[-1].split(":")[0]
    if len(parts) > 1 and ("." in parts[0] or ":" in parts[0] or parts[0] == "localhost"):
        parts = parts[1:]
    return "/".join(parts[-2:]) if len(parts) > 1 else parts[0]


def answered_image(t: dict, n: str | None, v: dict | None = None) -> str:
    v = v or t["nodes"][n]
    image = v["image"] or f"example/{t['app']}/{v['label']}:built"      # an application's own: its kind is not shared
    return image.split("@")[0] + "@sha256:" + "0" * 64


class Prior:
    """How likely a service calls another, from the training systems by the services' kinds: (calls + w g) / (pairs + w),
    g the share of all ordered pairs that call. A kind seen in only one training application is "other" (an
    application's own image says nothing about another's), and so is a service whose image is not known yet."""

    def __init__(self, systems: list[dict], weight: float = 2.0):
        apps = defaultdict(set)
        for t in systems:
            for v in t["nodes"].values():
                apps[kind(answered_image(t, None, v))].add(t["app"])
        self.shared = {k for k, a in apps.items() if len(a) > 1}
        calls, pairs = defaultdict(int), defaultdict(int)
        for t in systems:
            k = {n: self.kind(answered_image(t, None, v)) for n, v in t["nodes"].items()}
            for a in t["nodes"]:
                for b in t["nodes"]:
                    if a != b:
                        pairs[(k[a], k[b])] += 1
                        calls[(k[a], k[b])] += (a, b) in t["edges"]
        self.g = sum(calls.values()) / max(1, sum(pairs.values()))
        self.calls, self.pairs, self.w = calls, pairs, weight

    def kind(self, image: str | None) -> str:
        k = kind(image)
        return k if k in self.shared else "other"

    def __call__(self, iv: "Interview", a: str, b: str) -> float:
        ka, kb = self.kind(iv.image.get(a)), self.kind(iv.image.get(b))
        return (self.calls[(ka, kb)] + self.w * self.g) / (self.pairs[(ka, kb)] + self.w)


def tokens(label: str) -> list[str]:
    return [w for w in re.split(r"[^a-z]+", label.lower()) if w]


class Names:
    """The second prior, designed after the first (Prior) gained nothing; both are reported. What the interviewer
    knows from the start, the services' names: a pair is described by whether the two names share a word other than
    their last (user-timeline-service, user-timeline-redis), and by each name's last word where the training
    applications share it (redis, mongodb, service), else "other". Rates by description from the training systems,
    backed off to the rate for sharing a word or not."""

    def __init__(self, systems: list[dict], weight: float = 2.0):
        apps = defaultdict(set)
        for t in systems:
            for v in t["nodes"].values():
                apps[(tokens(v["label"]) or ["?"])[-1]].add(t["app"])
        self.roles = {r for r, a in apps.items() if len(a) > 1}
        calls, pairs = defaultdict(int), defaultdict(int)
        for t in systems:
            for a in t["nodes"]:
                for b in t["nodes"]:
                    if a != b:
                        for key in self.keys(t["nodes"][a]["label"], t["nodes"][b]["label"]):
                            pairs[key] += 1
                            calls[key] += (a, b) in t["edges"]
        self.calls, self.pairs, self.w = calls, pairs, weight
        self.g = sum(calls[k] for k in calls if len(k) == 1) / max(1, sum(pairs[k] for k in pairs if len(k) == 1))

    def role(self, label: str) -> str:
        r = (tokens(label) or ["?"])[-1]
        return r if r in self.roles else "other"

    @staticmethod
    def share(la: str, lb: str) -> bool:
        ta, tb = tokens(la) or ["?"], tokens(lb) or ["?"]
        return bool((set(ta) & set(tb)) - {ta[-1], tb[-1]})

    def keys(self, la: str, lb: str) -> list[tuple]:
        sh = self.share(la, lb)
        return [(sh,), (sh, self.role(la), self.role(lb))]

    def __call__(self, iv: "Interview", a: str, b: str) -> float:
        short, full = self.keys(iv.t["nodes"][a]["label"], iv.t["nodes"][b]["label"])
        base = (self.calls[short] + self.w * self.g) / (self.pairs[short] + self.w)
        return (self.calls[full] + self.w * base) / (self.pairs[full] + self.w)


class Hindsight:
    """The answers known in advance, chosen by the same measure: what the measure could reach with a perfect prior.
    Not an interviewer, and not a proven optimum (another order could do better)."""

    def __init__(self, t: dict):
        self.edges = t["edges"]

    def __call__(self, iv: "Interview", a: str, b: str) -> float:
        return float((a, b) in self.edges)


# ------------------------------------------------------------------ the interview
class Interview:
    def __init__(self, t: dict, rules):
        self.t, self.rules, self.n = t, rules, 0
        self.system = encode.system_iri(t["name"])
        self.claims: list[dict] = []
        self.known: set[tuple[str, str]] = set()
        self.image: dict[str, str] = {}
        self.add(self.system, RDF_TYPE, entity=KKT + "ServiceTemplate")
        for n, v in t["nodes"].items():                       # what the person says first: the services, by name
            self.add(n, RDF_TYPE, entity=KKT + "NodeTemplate")
            self.add(n, LABEL, value=v["label"])
            self.add(n, KKT + "memberOf", entity=self.system)

    def add(self, s, p, entity=None, value=None, qualifiers=None) -> None:
        self.n += 1
        self.claims.append({"id": str(self.n), "subject": s, "predicate": p, "object_entity": entity,
                            "object_value": None if value is None else {"@value": value}, "qualifiers": qualifiers or {}})

    def connect(self, a: str, b: str) -> None:
        if (a, b) not in self.known:
            self.known.add((a, b))
            self.add(a, KKT + "connectsTo", entity=b)

    def gaps(self) -> list[dict]:
        return finder.gaps(self.claims, self.rules)

    def answer(self, gap: dict) -> None:
        t, x, k = self.t, gap["target"], gap["kind"][len(GAP):]
        if k in ("no-image", "unpinned-image"):
            self.image[x] = answered_image(t, x)
            self.add(x, KKT + "propertyValue", value=self.image[x], qualifiers={KKT + "propertyName": "image"})
        elif k == "unconnected":
            for a, b in sorted(t["edges"]):
                if x in (a, b):
                    self.connect(a, b)
        elif k == "no-limit" and x == self.system:
            entry = next((n for n in t["nodes"] if not any(b == n for _, b in t["edges"])), sorted(t["nodes"])[0])
            self.add(entry, MAX, value=0.3, qualifiers={OBSERVED: LATENCY})
        elif k == "no-limit":
            callers = sorted(a for a, b in t["edges"] if b == x)
            for a in callers:
                self.connect(a, x)
            if not callers:
                self.add(x, MAX, value=0.3, qualifiers={OBSERVED: LATENCY})
        else:
            raise SystemExit(f"{t['name']}: no simulated answer to a {k} gap ({gap['text']})")


def expected(gap: dict, open_: list[dict], iv: Interview, prior) -> float:
    """How many open gaps answering this one is expected to close: itself, and for a connection question the other
    services' "unconnected" gaps it would close and the "no-limit" gaps of services it calls; for a limit question
    on a service something may call, the callers' "unconnected" gaps."""
    x, k = gap["target"], gap["kind"][len(GAP):]
    unconnected = {g["target"] for g in open_ if g["kind"] == GAP + "unconnected"} - {x}
    no_limit = {g["target"] for g in open_ if g["kind"] == GAP + "no-limit"} - {x}
    if k == "unconnected":
        either = sum(1 - (1 - prior(iv, x, y)) * (1 - prior(iv, y, x)) for y in unconnected)
        calls = sum(prior(iv, x, y) for y in no_limit)
        return 1 + either + calls
    if k == "no-limit" and x != iv.system:
        return 1 + sum(prior(iv, y, x) for y in unconnected)
    return 1.0


def interview(t: dict, rules, how: str, prior: Prior | None = None, seed: int = 0, limit: int = 1000) -> dict:
    iv, rng = Interview(t, rules), random.Random(seed)
    asked: dict[str, int] = defaultdict(int)
    order: list[str] = []
    while True:
        open_ = iv.gaps()
        if not open_:
            break
        if how == "fixed":
            gap = open_[0]
        elif how == "random":
            gap = rng.choice(open_)
        elif how == "ranked-images" and any(g["kind"].endswith("image") for g in open_):
            gap = next(g for g in open_ if g["kind"].endswith("image"))
        elif how in ("ranked", "ranked-images", "names", "hindsight"):
            gap = max(enumerate(open_), key=lambda ig: (expected(ig[1], open_, iv, prior), -ig[0]))[1]
        else:
            raise ValueError(how)
        asked[gap["kind"][len(GAP):]] += 1
        order.append(f"{gap['kind'][len(GAP):]} {gap['target'].rsplit(':', 1)[-1]}")
        iv.answer(gap)
        if len(order) > limit:
            raise SystemExit(f"{t['name']}: {how} did not finish in {limit} questions: {order[-5:]}")
    return {"questions": len(order), "by_kind": dict(asked), "unknown": len(t["edges"] - iv.known), "order": order}


def training(systems: list[dict], t: dict) -> list[dict]:
    """What a prior may learn from when t is interviewed: every other application, never t's own."""
    return [s for s in systems if s["app"] != t["app"]]


def run(systems: list[dict], seeds: int, only: str | None = None) -> list[dict]:
    """Each system (or only those whose application names `only`), its prior learned from all the other applications."""
    rules = finder.shapes()
    out = []
    for t in (t for t in systems if not only or only in t["app"]):
        train = training(systems, t)
        prior = Prior(train)
        row = {"app": t["app"], "file": t["file"], "services": len(t["nodes"]), "connections": len(t["edges"]),
               "fixed": interview(t, rules, "fixed"), "ranked": interview(t, rules, "ranked", prior),
               "ranked-images": interview(t, rules, "ranked-images", prior),
               "names": interview(t, rules, "names", Names(train)), "hindsight": interview(t, rules, "hindsight", Hindsight(t))}
        rs = [interview(t, rules, "random", seed=s) for s in range(seeds)]
        row["random"] = {"mean": sum(r["questions"] for r in rs) / len(rs), "min": min(r["questions"] for r in rs),
                         "max": max(r["questions"] for r in rs), "unknown": sum(r["unknown"] for r in rs) / len(rs)}
        out.append(row)
        print(f"{t['app']:40s} {row['services']:3d} services {row['connections']:3d} conn | "
              + " | ".join(f"{h} {row[h]['questions']} ({row[h]['unknown']} unknown)" for h in ("fixed", "ranked", "ranked-images", "names", "hindsight"))
              + f" | random {row['random']['mean']:.1f} [{row['random']['min']}-{row['random']['max']}]", flush=True)
    return out


def verdict(rows: list[dict], how: str = "ranked") -> tuple[bool, str]:
    big = [r for r in rows if r["services"] >= 10]
    f, r = sum(x["fixed"]["questions"] for x in big), sum(x[how]["questions"] for x in big)
    fu, ru = sum(x["fixed"]["unknown"] for x in big), sum(x[how]["unknown"] for x in big)
    keep = bool(big) and r <= 0.9 * f and ru <= fu
    return keep, (f"{how}: systems of 10 or more services: {len(big)}; questions fixed {f}, {how} {r} ({(r - f) / max(f, 1):+.1%}); "
                  f"connections unknown at the end fixed {fu}, {how} {ru}: "
                  + ("the measure with the answers known, not an interviewer" if how == "hindsight" else "kept" if keep else "dropped"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("what", choices=["fetch", "run"])
    ap.add_argument("--seeds", type=int, default=20)
    ap.add_argument("--only")
    ap.add_argument("--json")
    a = ap.parse_args()
    if a.what == "fetch":
        return fetch()
    systems = corpus()
    if not systems:
        raise SystemExit(f"no corpus in {CACHE}: run `fetch` first")
    rows = run(systems, a.seeds, a.only)
    for how in ("ranked", "ranked-images", "names", "hindsight"):
        print(verdict(rows, how)[1])
    if a.json:
        Path(a.json).write_text(json.dumps({"corpus": CORPUS, "seeds": a.seeds, "verdicts": [verdict(rows, h)[1] for h in
                                            ("ranked", "ranked-images", "names", "hindsight")], "systems": rows}, indent=1))


if __name__ == "__main__":
    main()
