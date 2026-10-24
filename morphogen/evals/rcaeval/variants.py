"""Statistics tried for the analyser on RE1 (the tuning set) without touching the module; EXPERIMENTS.md has the
results.  python3.12 morphogen/evals/rcaeval/variants.py DATASET STAT

  STAT  mean       the analyser's statistic (mean, population sd; None when sd is 0)
        mean-fb    the same, with rebuild 4's fallbacks for a flat history (|mean|/10, else 1.0)
        mean-fb10  mean-fb without the last fallback (a history flat at 0 still has no score)
        robust-slide  median and IQR (else sd, else |median|/10; None when all are 0)
        robust-fb  the same, with the last fallback 1.0, as rebuild 4's robust_z
        <stat>-excl  a window scored above 3 is left out of the history after it
        r4-unrounded  rebuild 4's method (run.py robust) without rounding scores to one decimal
Each runs over the analyser's sliding history (up to 20 previous windows, at least 5), as run.py's analyser does.
"""
import sys, importlib.util, statistics
from pathlib import Path
import numpy as np
spec = importlib.util.spec_from_file_location("rc", Path(__file__).resolve().parent / "run.py")
rc = importlib.util.module_from_spec(spec); spec.loader.exec_module(rc)
STAT = sys.argv[2]

def robust(values, v):
    if len(values) < 5: return None
    a = np.array(values); med = np.median(a)
    scale = np.subtract(*np.percentile(a, [75, 25])) or np.std(a) or abs(med) * 0.1
    return abs(v - med) / scale if scale else None

def mean_sd(values, v):
    if len(values) < 5: return None
    m, sd = statistics.fmean(values), statistics.pstdev(values)
    return abs(v - m) / sd if sd > 0 else None

EXCL = STAT.endswith("-excl")
def mean_fb(values, v):
    if len(values) < 5: return None
    m, sd = statistics.fmean(values), statistics.pstdev(values)
    return abs(v - m) / (sd or abs(m) * 0.1 or 1.0)

def mean_fb10(values, v):
    if len(values) < 5: return None
    m, sd = statistics.fmean(values), statistics.pstdev(values)
    scale = sd or abs(m) * 0.1
    return abs(v - m) / scale if scale else None

def robust_fb(values, v):
    if len(values) < 5: return None
    a = np.array(values); med = np.median(a)
    scale = np.subtract(*np.percentile(a, [75, 25])) or np.std(a) or abs(med) * 0.1 or 1.0
    return abs(v - med) / scale

if STAT == "r4-unrounded":
    import re as _re, inspect
    src = inspect.getsource(rc.robust_method).replace("abs(round(float(z[int(np.nanargmax(np.abs(z)))]), 1))",
                                                       "abs(float(z[int(np.nanargmax(np.abs(z)))]))")
    exec(src, rc.__dict__)
    res = rc.run(sys.argv[1], "robust", 60)
    print(STAT, sys.argv[1], res["avg@5"], res["avg@5_mean"]); sys.exit()
stat = {"robust-slide": robust, "mean": mean_sd, "mean-fb": mean_fb, "mean-fb10": mean_fb10, "robust-fb": robust_fb}[STAT.replace("-excl", "")]
def factory(window):
    def method(data, inject_time=None, dataset=None, **kw):
        means = rc.windows(data, inject_time, window); scores = {}
        for col in means.columns:
            s = means[col].dropna(); best = 0.0; hist = []
            for w, v in s.items():
                z = stat(hist[-20:], float(v))
                if w >= 0: best = max(best, z or 0.0)
                if not (EXCL and z is not None and z > 3): hist.append(float(v))
            scores[col] = best
        r = sorted(scores, key=lambda c: -scores[c]); return {"node_names": r, "ranks": r}
    return method
rc.robust_method = factory   # reuse the 'robust' slot to run this variant
res = rc.run(sys.argv[1], "robust", 60)
print(STAT, sys.argv[1], res["avg@5"], res["avg@5_mean"])
