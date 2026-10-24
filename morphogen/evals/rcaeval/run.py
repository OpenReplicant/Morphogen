"""RCAEval on the analyser (rebuild 4 eval/rcaeval, M3-T8, D-63, D-65): does telemetry aggregated per window,
as the observer records it, and the analyser's own statistic, find a fault's root cause?

  python3.12 morphogen/evals/rcaeval/run.py fetch                      RCAEval's main.py at the pinned commit
  python3.12 morphogen/evals/rcaeval/run.py run --dataset re1-ob --method analyser [--window 60]
  python3.12 morphogen/evals/rcaeval/run.py run --dataset re1-ob --method robust   rebuild 4's `kernel` method
  python3.12 morphogen/evals/rcaeval/run.py run --dataset re1-ob --method baro     a published baseline

Runs RCAEval's own main.py (data download, the injection time, preprocessing, Avg@5 scoring) unchanged; our
methods stand in for its `dummy` slot, as rebuild 4's did. The data are RCAEval's (MIT, Pham et al., WWW 2025
Companion): RE1 has 375 injected faults (CPU, memory, disk, delay, loss) on Online Boutique, Sock Shop and
Train Ticket, metrics only; every method gets the injection time and ranks metrics; Avg@5 is the mean of
AC@1..AC@5 for the root-cause service.

  analyser  each metric averaged over windows of --window seconds aligned to the injection (the observer's
            KK_WINDOW_SECONDS), then, for each window after the injection, the analyser's own z-score
            (morphogen/modules/anomaly detect.zscore: mean and standard deviation of up to 20 previous windows,
            at least 5; a flat history scaled by a tenth of its mean, else 1, R5-28) as its passes would
            compute it; metrics ranked by their largest
  robust    rebuild 4's `kernel` method (eval/rcaeval/packs.py zscores): the same windows, then each metric's
            largest robust z (median, IQR, with fallbacks for flat baselines) after the injection against the
            windows before it. Rebuild 4's floor is this method's numbers

Needs Python 3.12 (RCAEval's main.py refuses 3.13) with requirements.txt here (RCAEval with --no-deps). KK_EVAL_CACHE holds main.py and
the data (never committed). Results go to morphogen/evals/rcaeval/runs/<date>-<dataset>-<method>.json; EXPERIMENTS.md
records every statistic tried (variants.py) and what was chosen.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import runpy
import shutil
import sys
import urllib.request
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CACHE = Path(os.environ.get("KK_EVAL_CACHE") or Path.home() / ".cache/knowledge-kernel/eval") / "rcaeval"
COMMIT = "259ea4167160256a74ad30004aa3d96a998c846e"      # rebuild 4's pin
MAIN = (f"https://raw.githubusercontent.com/phamquiluan/RCAEval/{COMMIT}/main.py",
        "4e527f1f16736ef8353f7372bdbbd24270e6a383edb00f3a34b7a599d429e0e0")
FLOOR = {  # rebuild 4, eval/rcaeval/runs/2026-10-17-*-kernel-w60.json (Avg@5 mean); its re2-tt had 63 of 90 cases
    "re1-ob": 0.894, "re1-ss": 0.922, "re1-tt": 0.800, "re2-ob": 0.935, "re2-tt": 0.643}
SPAN = 600           # seconds before and after the injection, as RCAEval's default length (20 minutes)


def fetch() -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    main = CACHE / "main.py"
    if not main.exists():
        data = urllib.request.urlopen(MAIN[0], timeout=60).read()
        if hashlib.sha256(data).hexdigest() != MAIN[1]:
            raise SystemExit(f"main.py from {MAIN[0]} does not match its pinned sha256")
        main.write_bytes(data)
    return main


def windows(frame, inject: int, window: int):
    """Each metric's mean per window of `window` seconds, aligned to the injection (window 0 starts there)."""
    frame = frame[(frame["time"] >= inject - SPAN) & (frame["time"] < inject + SPAN)].copy()
    frame["window"] = (frame["time"] - inject) // window
    return frame.drop(columns="time").groupby("window").mean(numeric_only=True)


def analyser_method(window: int):
    """The analyser's own statistic on each window after the injection, as its passes would see them."""
    sys.path.insert(0, str(ROOT / "morphogen" / "modules" / "anomaly"))
    from anomaly.detect import HISTORY, zscore

    def method(data, inject_time=None, dataset=None, **kwargs):
        means = windows(data, inject_time, window)
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
        ranks = sorted(scores, key=lambda c: -scores[c])
        return {"node_names": ranks, "ranks": ranks}
    return method


def robust_method(window: int):
    """Rebuild 4's `kernel` method (eval/rcaeval/packs.py robust_z and zscores), ported unchanged."""
    import numpy as np

    def robust_z(before, after):
        med = np.median(before)
        scale = np.subtract(*np.percentile(before, [75, 25])) or np.std(before) or abs(med) * 0.1 or 1.0
        return (after - med) / scale

    def method(data, inject_time=None, dataset=None, **kwargs):
        means = windows(data, inject_time, window)
        before, after = means[means.index < 0], means[means.index >= 0]
        scores = {}
        for col in means.columns:
            a, b = before[col].dropna().to_numpy(), after[col].dropna().to_numpy()
            if len(a) < 2 or len(b) < 1 or np.all(a == a[0]) and np.all(b == a[0]):
                continue
            z = robust_z(a, b)
            scores[col] = abs(round(float(z[int(np.nanargmax(np.abs(z)))]), 1))   # rounded as rebuild 4's packs did
        ranks = sorted(scores, key=lambda c: -scores[c])
        return {"node_names": ranks, "ranks": ranks}
    return method


def run(dataset: str, method: str, window: int) -> dict:
    main = fetch()
    os.chdir(CACHE)
    shutil.rmtree(CACHE / "output" / "results", ignore_errors=True)   # main.py scores every file left there (D-65)
    name = method
    if method in ("analyser", "robust"):
        import RCAEval.e2e as e2e
        e2e.dummy = (analyser_method if method == "analyser" else robust_method)(window)
        name, method = f"{method}-w{window}", "dummy"
    sys.argv = ["main.py", "--method", method, "--dataset", dataset, "--report-chance"]
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
        runpy.run_path(str(main), run_name="__main__")
    text = out.getvalue()
    scores = {m.group(1): float(m.group(2)) for m in re.finditer(r"^Avg@5-(\w+):\s+([\d.]+)", text, re.M)}
    chance = {m.group(1): float(m.group(2)) for m in re.finditer(r"^Chance@5-(\w+):\s+([\d.]+)", text, re.M)}
    if not scores:
        raise SystemExit(text[-2000:])
    mean = round(sum(scores.values()) / len(scores), 4)
    detect = ROOT / "morphogen" / "modules" / "anomaly" / "anomaly" / "detect.py"
    rules = re.search(r"^version: (\S+)", (ROOT / "morphogen" / "contract" / "slots" / "analyser" / "set.yaml").read_text(), re.M)
    from importlib.metadata import version
    return {"benchmark": "RCAEval", "dataset": dataset, "method": name, "avg@5": scores, "avg@5_mean": mean,
            "chance@5": chance, "floor": {"rebuild4_kernel_w60": FLOOR.get(dataset)},
            "rcaeval": {"commit": COMMIT, "main_sha256": MAIN[1], "package": "RCAEval 1.8.1 (PyPI)"},
            "analyser": {"detect_sha256": hashlib.sha256(detect.read_bytes()).hexdigest(), "slot_set": rules.group(1)},
            "packages": {p: version(p) for p in ("numpy", "pandas", "scipy", "scikit-learn")}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("fetch")
    r = sub.add_parser("run")
    r.add_argument("--dataset", required=True)
    r.add_argument("--method", default="analyser", choices=["analyser", "robust", "baro", "nsigma"])
    r.add_argument("--window", type=int, default=60)
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        print(fetch())
        return 0
    result = run(a.dataset, a.method, a.window)
    (HERE / "runs").mkdir(exist_ok=True)
    out = HERE / "runs" / f"{date.today().isoformat()}-{a.dataset}-{result['method']}.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: result[k] for k in ("dataset", "method", "avg@5", "avg@5_mean", "floor")}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
