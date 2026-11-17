"""Paired, per-case comparison of a candidate against its base.

Each KPI gives one number per case for each run. The judge pairs them by case id and works on the
per-case improvement d = candidate - base (or base - candidate when lower is better), so positive
is always better.

- A deciding KPI passes when an exact one-sided sign test rejects "no better" at alpha and the mean
  improvement reaches the card's floor.
- A bounding KPI passes when a paired bootstrap lower confidence bound (one-sided, 1 - alpha) on the
  mean improvement is no worse than minus the card's tolerance.
- The minimum detectable effect is stated from the case count before any run: the sign test can only
  reject when at least k = ceil(log2(1/alpha)) cases improve, so no candidate can show an effect
  smaller than k of the N cases. For a 0/1 KPI that is k/N in the KPI's own units.

There is no extend-while-undecided rule: each verdict sees one fixed case set, so no correction for
sequential looks is needed. If one is added, this module must correct for it (and A/A must be rerun).
"""

import math
import random

BOOTSTRAP = 10_000


def sign_test(better, worse):
    """P(X >= better) for X ~ Binomial(better + worse, 1/2): one-sided, exact."""
    n = better + worse
    if n == 0:
        return 1.0
    return sum(math.comb(n, i) for i in range(better, n + 1)) / 2 ** n


def min_wins(alpha):
    return max(1, math.ceil(math.log2(1 / alpha)))


def mde(n_cases, alpha):
    """Smallest share of cases that must improve (with none worse) for the sign test to reject."""
    k = min_wins(alpha)
    return None if n_cases < k else k / n_cases


def bootstrap_bounds(d, alpha, rng):
    n = len(d)
    if n == 0:
        return None
    means = sorted(math.fsum(rng.choices(d, k=n)) / n for _ in range(BOOTSTRAP))
    lo = means[max(0, math.floor(alpha * BOOTSTRAP) - 1)]
    hi = means[min(BOOTSTRAP - 1, math.ceil((1 - alpha) * BOOTSTRAP) - 1)]
    return [lo, hi]


def judge_kpi(kpi, expected_ids, base, cand, alpha, rng):
    """kpi: the card's KPI. base, cand: {case_id: value} measured by the judge. Returns a kpi_result."""
    expected = len(expected_ids)
    b = {i: base[i] for i in expected_ids if base.get(i) is not None}
    c = {i: cand[i] for i in expected_ids if cand.get(i) is not None}
    sign = 1 if kpi["direction"] == "higher" else -1
    out = {
        "name": kpi["name"], "source": kpi["source"], "direction": kpi["direction"], "role": kpi["role"],
        "floor": kpi["floor"], "expected": expected,
        "base": {"seen": len(b), "mean": sum(b.values()) / len(b) if b else None},
        "candidate": {"seen": len(c), "mean": sum(c.values()) / len(c) if c else None},
        "paired": {"n": 0, "better": 0, "worse": 0, "tied": 0},
        "effect": None, "interval": None, "p_value": None, "mde": mde(expected, alpha),
        "method": f"exact one-sided sign test; paired bootstrap ({BOOTSTRAP} resamples) one-sided bounds",
    }
    # The base runs first and the candidate cannot touch its run, so a short base run is the judge's
    # failure (stop), checked first; a short candidate run is the candidate's (refuse).
    if len(b) < expected:
        return {**out, "result": "stop", "reason": f"base's run gave {len(b)} of {expected} cases; judgment stops"}
    if len(c) < expected:
        return {**out, "result": "refuse", "reason": f"candidate's run gave {len(c)} of {expected} cases"}
    if expected == 0:
        return {**out, "result": "stop", "reason": "the case set is empty"}
    d = [sign * (c[i] - b[i]) for i in expected_ids]
    better, worse = sum(x > 0 for x in d), sum(x < 0 for x in d)
    effect = sum(d) / len(d)
    out.update(paired={"n": len(d), "better": better, "worse": worse, "tied": len(d) - better - worse},
               effect=effect, interval=bootstrap_bounds(d, alpha, rng), p_value=sign_test(better, worse))
    if kpi["role"] == "decide":
        if out["p_value"] > alpha:
            return {**out, "result": "refuse",
                    "reason": f"not shown better: sign test p={out['p_value']:.4g} > alpha={alpha} ({better} better, {worse} worse)"}
        if effect < kpi["floor"]:
            return {**out, "result": "refuse", "reason": f"mean improvement {effect:.4g} is below the floor {kpi['floor']}"}
        return {**out, "result": "pass", "reason": f"better: p={out['p_value']:.4g}, mean improvement {effect:.4g}"}
    lo = out["interval"][0]
    if lo < -kpi["floor"]:
        return {**out, "result": "refuse",
                "reason": f"may be worse than tolerated: lower bound {lo:.4g} < -{kpi['floor']}"}
    return {**out, "result": "pass", "reason": f"within tolerance: lower bound {lo:.4g} >= -{kpi['floor']}"}


def new_rng(seed=None):
    """The judge's own randomness. Never seeded from anything the candidate can choose (its commit hash)."""
    return random.Random(seed if seed is not None else random.SystemRandom().getrandbits(64))
