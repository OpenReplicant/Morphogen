"""Map-aware ordering of the analyser's root-cause candidates (T19, R5-O7 a2), tried on RE1 (the tuning set,
D-64); EXPERIMENTS.md has the results.  python3.12 morphogen/evals/rcaeval/map_order.py DATASET RULE THRESHOLD

The scores are the analyser's (run.py analyser, 60 s windows); only the order changes. A service's
dependencies are the transitive closure of who it calls (kk.graph.closure over the map below).
  RULE  none     the analyser's order
        any      a metric whose service depends on a service scoring >= THRESHOLD ranks below every other
        higher   the same, only when that dependency scores at least as high as the metric itself
        lat      only latency and error metrics are moved, and only by a dependency's latency or error
        latpen   lat, as a penalty (the score halved) rather than a move to the end
MAPS: Online Boutique only, from the `*_ADDR` environment of each Deployment in
https://raw.githubusercontent.com/GoogleCloudPlatform/microservices-demo/v0.8.0/release/kubernetes-manifests.yaml
(redis-cart is the dataset's `redis`). The rules lost on RE1-OB, so no map was written for Sock Shop or Train Ticket.
"""
import sys
import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
spec = importlib.util.spec_from_file_location("rc", HERE / "run.py")
rc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rc)
sys.path[:0] = [str(ROOT / "morphogen" / "modules" / "anomaly"), str(ROOT / "kernel" / "src")]
from anomaly.detect import HISTORY, zscore  # noqa: E402
from kk.graph import closure  # noqa: E402

OB = {"frontend": ["adservice", "cartservice", "checkoutservice", "currencyservice", "productcatalogservice",
                   "recommendationservice", "shippingservice"],
      "checkoutservice": ["cartservice", "currencyservice", "emailservice", "paymentservice", "productcatalogservice",
                          "shippingservice"],
      "recommendationservice": ["productcatalogservice"], "cartservice": ["redis"]}
MAPS = {"re1-ob": OB}      # RE2 (held out) was not used: the rules lost on RE1
SIGNAL = ("latency", "error")


def factory(rule: str, threshold: float, edges: list):
    def deps(s):
        return set(closure(edges, s))

    def method(window):
        def ranked(data, inject_time=None, dataset=None, **kwargs):
            means = rc.windows(data, inject_time, window)
            scores = {}
            for col in means.columns:
                series = means[col].dropna()
                best = 0.0
                for i, (w, v) in enumerate(series.items()):
                    if w < 0:
                        continue
                    z = zscore([float(x) for x in series.iloc[max(0, i - HISTORY):i]], float(v))
                    best = max(best, z or 0.0)
                scores[col] = best
            svc = lambda c: c.rsplit("_", 1)[0]  # noqa: E731
            signal = lambda c: c.rsplit("_", 1)[-1].startswith(SIGNAL)  # noqa: E731
            per, sig = {}, {}
            for c, v in scores.items():
                per[svc(c)] = max(per.get(svc(c), 0.0), v)
                if signal(c) and v >= threshold:
                    sig[svc(c)] = max(sig.get(svc(c), 0.0), v)

            def moved(c):
                if rule == "any":
                    return any(per.get(d, 0.0) >= threshold for d in deps(svc(c)))
                if rule == "higher":
                    return any(per.get(d, 0.0) >= max(threshold, scores[c]) for d in deps(svc(c)))
                if rule in ("lat", "latpen"):
                    return signal(c) and any(sig.get(d, 0.0) >= scores[c] for d in deps(svc(c)))
                return False
            if rule == "latpen":
                ranks = sorted(scores, key=lambda c: -scores[c] * (0.5 if moved(c) else 1.0))
            else:
                ranks = sorted(scores, key=lambda c: (moved(c), -scores[c]))
            return {"node_names": ranks, "ranks": ranks}
        return ranked
    return method


if __name__ == "__main__":
    dataset, rule, threshold = sys.argv[1], sys.argv[2], float(sys.argv[3])
    edges = [(s, o, f"{s}>{o}") for s, os_ in MAPS.get(dataset, {}).items() for o in os_]
    rc.analyser_method = factory(rule, threshold, edges)
    res = rc.run(dataset, "analyser", 60)
    print(rule, threshold, dataset, res["avg@5"], res["avg@5_mean"])
