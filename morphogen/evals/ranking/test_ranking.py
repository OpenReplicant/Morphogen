"""The ranking test's simulation (run.py) on a hand-made system, against counts worked out by hand; no corpus, no
database.

  python3 morphogen/evals/ranking/test_ranking.py

The system: web calls svc, svc calls cache and db. The person first names the four services; the gap finder then
asks for four images, and whether each service connects, and a limit for each service nothing calls.
  fixed      4 images; "unconnected" in target order: cache (svc-cache), db (svc-db), web (web-svc): 3; then the one
             service nothing calls, web, its limit: 1. 8 questions, no connection left unknown.
  hindsight  svc first (closes its own gap, three others' and the no-limit gaps of cache and db: expected 6), then
             in the fixed order: 4 images, web's limit. 6.
A second: z calls m and a, m calls a. Asked first, a's connections (m-a, z-a) leave z-m unknown, so m has no known
caller; asked for m's limit, the person says z calls it. 3 images, 1 connection question, m's and z's limits: 6.
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run as R  # noqa: E402

N = "urn:kk:node:shop:"


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def system(app: str, name: str, images: dict[str, str | None], edges: list[tuple[str, str]]) -> dict:
    n = f"urn:kk:node:{name}:"
    return {"app": app, "file": app, "name": name, "edges": {(n + a, n + b) for a, b in edges},
            "nodes": {n + k: {"label": k, "image": v} for k, v in images.items()}}


SHOP = system("hand/shop", "shop", {"web": "nginx:1.27", "svc": None, "cache": "redis:7", "db": "postgres:16"},
              [("web", "svc"), ("svc", "cache"), ("svc", "db")])


def main() -> None:
    check([R.kind(i) for i in ("postgres:16.4@sha256:" + "0" * 64, "ghcr.io/example/notes-web:1.4.2", "redis",
                               "localhost:5000/team/app:1", "deathstarbench/social-network-microservices:latest")]
          == ["postgres", "example/notes-web", "redis", "team/app", "deathstarbench/social-network-microservices"],
          "an image's kind: its name without registry, tag or digest")
    rules = R.finder.shapes()
    fixed = R.interview(SHOP, rules, "fixed")
    check(fixed["by_kind"] == {"no-image": 4, "unconnected": 3, "no-limit": 1} and fixed["unknown"] == 0,
          f"the fixed order: 4 images, 3 connection questions, 1 limit ({fixed['order']})")
    check([o for o in fixed["order"] if not o.startswith("no-image")] == ["unconnected cache", "unconnected db", "unconnected web",
                                                                          "no-limit web"], "asked in the gap finder's order")
    iv = R.Interview(SHOP, rules)
    open_ = iv.gaps()
    svc = next(g for g in open_ if g["kind"].endswith("unconnected") and g["target"] == N + "svc")
    check(R.expected(svc, open_, iv, R.Hindsight(SHOP)) == 6, "knowing the answers, asking svc closes 6 gaps")
    hind = R.interview(SHOP, rules, "hindsight", R.Hindsight(SHOP))
    check(hind["questions"] == 6 and hind["order"][0] == "unconnected svc" and hind["unknown"] == 0,
          f"knowing the answers, svc first: 6 questions ({hind['order']})")
    tri = system("hand/tri", "tri", {"a": "postgres:16", "m": None, "z": "nginx:1"}, [("z", "m"), ("z", "a"), ("m", "a")])
    got = R.interview(tri, rules, "fixed")
    check(got["order"][3:] == ["unconnected a", "no-limit m", "no-limit z"] and got["unknown"] == 0,
          f"a limit question about a service something calls is answered with its callers ({got['order']}, {got['unknown']} unknown)")
    a = system("hand/a", "a", {"web": "nginx:1", "app": None, "db": "postgres:15"}, [("web", "app"), ("app", "db")])
    b = system("hand/b", "b", {"proxy": "nginx:1", "api": None, "db": "postgres:16", "jobs": None}, [("proxy", "api"), ("api", "db")])
    p = R.Prior([a, b])
    check(p.shared == {"nginx", "postgres"}, f"kinds seen in two applications are kept, the rest are other ({sorted(p.shared)})")
    check(abs(p.g - 4 / 18) < 1e-9, f"g: 4 calls in 6 + 12 ordered pairs ({p.g})")
    iv = R.Interview(SHOP, rules)
    iv.image = {N + "web": "nginx:1", N + "svc": "example/svc:built", N + "db": "postgres:16"}
    # nginx -> other: 2 calls in 3 pairs (a: web-app; b: proxy-api, proxy-jobs); postgres -> anything: 0 in 5
    check(abs(p(iv, N + "web", N + "svc") - (2 + 2 * p.g) / (3 + 2)) < 1e-9 and abs(p(iv, N + "db", N + "svc") - 2 * p.g / (3 + 2)) < 1e-9,
          "a pair's rate is its kinds' calls over pairs, smoothed toward g")
    check(abs(p(iv, N + "cache", N + "svc") - (p.calls[("other", "other")] + 2 * p.g) / (p.pairs[("other", "other")] + 2)) < 1e-9,
          "a service whose image is not known yet is other")
    check(R.Names.share("user-timeline-service", "user-timeline-redis") and not R.Names.share("text-service", "media-service"),
          "two names share a word other than their last")
    # With the images known (asked first), the prior trained on a and b: nginx calls "other" services (2 of 3 pairs),
    # postgres calls nothing. Expected gaps closed, worked out by hand: web 3.37, cache and svc 2.97, db 2.57, so web
    # first (fixed asks cache); then cache 2.11 over db 1.73, then db, then web's limit. 8 questions.
    got = R.interview(SHOP, rules, "ranked-images", p)
    check(got["order"][4:] == ["unconnected web", "unconnected cache", "unconnected db", "no-limit web"] and got["questions"] == 8,
          f"ranked with the images first: the prior's kinds pick web first ({got['order']})")
    got = R.interview(SHOP, rules, "ranked", p)
    check(all(not o.startswith("no-image") for o in got["order"][:3]),
          f"ranked as decided: connection questions before images, so its prior sees only other ({got['order']})")
    check([s["app"] for s in R.training([a, b, SHOP], SHOP)] == ["hand/a", "hand/b"]
          and [s["app"] for s in R.training([a, b, SHOP], a)] == ["hand/b", "hand/shop"],
          "a prior never learns from the application interviewed")
    with tempfile.TemporaryDirectory() as d:
        root = Path(d)
        def put(rel, text):
            (root / rel).parent.mkdir(parents=True, exist_ok=True)
            (root / rel).write_text(text)
        two = "services:\n  a:\n    image: x\n    depends_on: [b]\n  b:\n    image: y\n"
        three = two + "  c:\n    image: z\n    depends_on: [b]\n"
        four = three + "  d:\n    image: w\n    depends_on: [b]\n"
        put("DeathStarBench/app1/docker-compose-sharding.yml", two)        # sorts first; fewer connections
        put("DeathStarBench/app1/docker-compose.yml", three)
        put("DeathStarBench/app1/openshift/compose-x.yaml", four)          # an OpenShift directory is never a system
        put("awesome-compose/one/compose.yaml", two)
        put("awesome-compose/lonely/compose.yaml", "services:\n  a:\n    image: x\n")
        put("microservices-demo/deploy/docker-compose/docker-compose.yml", three)
        got = {t["app"]: (t["file"], len(t["nodes"])) for t in R.corpus(root)}
        check(got == {"DeathStarBench/app1": ("DeathStarBench/app1/docker-compose.yml", 3),
                      "awesome-compose/one": ("awesome-compose/one/compose.yaml", 2),
                      "microservices-demo/sock-shop": ("microservices-demo/deploy/docker-compose/docker-compose.yml", 3)},
              f"one system per application, its file with the most connections, OpenShift templates and lone services left out ({got})")
    rows = [{"services": 12, "fixed": {"questions": 100, "unknown": 3}, "ranked": {"questions": 90, "unknown": 3}},
            {"services": 3, "fixed": {"questions": 5, "unknown": 0}, "ranked": {"questions": 9, "unknown": 0}}]
    check(R.verdict(rows)[0], "kept at 10% fewer questions on the large systems, the small ones not counted")
    rows[0]["ranked"]["unknown"] = 4
    check(not R.verdict(rows)[0], "dropped when it leaves more connections unknown")
    rows[0]["ranked"].update(questions=91, unknown=3)
    check(not R.verdict(rows)[0], "dropped below 10% fewer")
    print("ranking checks passed")


if __name__ == "__main__":
    main()
