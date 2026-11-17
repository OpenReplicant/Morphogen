import math
import random

from judge import stats

DECIDE = {"name": "accuracy", "source": "scorer", "direction": "higher", "floor": 0.0, "role": "decide"}
BOUND = {"name": "wall_seconds", "source": "runner", "direction": "lower", "floor": 0.01, "role": "bound"}
IDS = [f"c{i}" for i in range(40)]


def run(kpi, base, cand, alpha=0.05, seed=1):
    return stats.judge_kpi(kpi, IDS, base, cand, alpha, stats.new_rng(seed))


def test_sign_test_is_exact():
    assert stats.sign_test(5, 0) == 1 / 32
    assert math.isclose(stats.sign_test(8, 2), sum(math.comb(10, i) for i in range(8, 11)) / 1024)
    assert stats.sign_test(0, 0) == 1.0


def test_mde_is_stated_from_the_case_count():
    assert stats.min_wins(0.05) == 5
    assert stats.mde(40, 0.05) == 5 / 40
    assert stats.mde(4, 0.05) is None  # too few cases to ever pass


def test_identical_outputs_never_pass():
    same = {i: 0.5 for i in IDS}
    assert run(DECIDE, same, dict(same))["result"] == "refuse"


def test_a_real_improvement_passes():
    base = {i: float(n % 2) for n, i in enumerate(IDS)}
    cand = {i: 1.0 for i in IDS}
    r = run(DECIDE, base, cand)
    assert r["result"] == "pass" and r["paired"] == {"n": 40, "better": 20, "worse": 0, "tied": 20}


def test_short_candidate_run_is_refused_and_short_base_run_stops():
    full = {i: 1.0 for i in IDS}
    short = {i: 1.0 for i in IDS[:-1]}
    assert run(DECIDE, {i: 0.0 for i in IDS}, short)["result"] == "refuse"
    assert run(DECIDE, {i: 0.0 for i in IDS[:-1]}, full)["result"] == "stop"


def test_extra_cases_the_candidate_adds_do_not_count():
    base = {i: 0.0 for i in IDS[:-1]} | {IDS[-1]: 1.0}
    cand = {i: 0.0 for i in IDS} | {f"fake{i}": 1.0 for i in range(100)}
    assert run(DECIDE, base, cand)["result"] == "refuse"


def test_bound_refuses_a_clear_slowdown_and_tolerates_noise():
    rnd = random.Random(3)
    base = {i: 0.1 + rnd.gauss(0, 0.002) for i in IDS}
    noisy = {i: 0.1 + rnd.gauss(0, 0.002) for i in IDS}
    slow = {i: 0.2 for i in IDS}
    assert run(BOUND, base, noisy)["result"] == "pass"
    assert run(BOUND, base, slow)["result"] == "refuse"


def test_a_a_rate(monkeypatch):
    """A/A: the same noisy program against itself, many times. Record how often it passes a deciding KPI."""
    monkeypatch.setattr(stats, "BOOTSTRAP", 100)  # the deciding rule does not use the bootstrap
    trials, passes = 2000, 0
    rnd = random.Random(11)
    for t in range(trials):
        base = {i: rnd.gauss(1.0, 0.1) for i in IDS}
        cand = {i: rnd.gauss(1.0, 0.1) for i in IDS}
        passes += stats.judge_kpi(DECIDE, IDS, base, cand, 0.05, stats.new_rng(t))["result"] == "pass"
    rate = passes / trials
    # The sign test is exact, so the false-pass rate must sit at or below alpha (plus sampling error).
    assert rate <= 0.05 + 3 * math.sqrt(0.05 * 0.95 / trials), rate
    print(f"A/A false-pass rate over {trials} trials, 40 cases, alpha 0.05: {rate:.4f}")
