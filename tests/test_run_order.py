"""The run harness pairs base and candidate case by case, in an order chosen by coin flip, so drift in
the machine's load over the run cannot turn into a difference between the sides (DECISIONS.md)."""

import io
import json

from judge import run


def test_pairs_are_adjacent_and_the_order_is_a_coin_flip(monkeypatch):
    calls = []
    monkeypatch.setattr(run, "run_case", lambda tag, module, payload, limits: calls.append((tag, payload)) or
                        {"exit": 0, "oom": False, "timed_out": False, "wall_seconds": 0.1, "output": "", "stderr_tail": ""})
    cases = [{"id": f"c{i}", "input": i} for i in range(400)]
    out = {"base": io.StringIO(), "candidate": io.StringIO()}
    run.run_pairs({"base": "B", "candidate": "C"}, "m", cases, {}, out)
    assert len(calls) == 800
    firsts = []
    for i in range(0, 800, 2):
        (t1, p1), (t2, p2) = calls[i], calls[i + 1]
        assert p1 == p2 and {t1, t2} == {"B", "C"}  # both sides of one case, back to back
        firsts.append(t1)
    assert 140 < firsts.count("B") < 260  # a fair coin: P(outside) < 1e-8
    recs = [json.loads(l) for l in out["base"].getvalue().splitlines()]
    assert [r["id"] for r in recs] == [c["id"] for c in cases]
    assert sum(r["ran_first"] for r in recs) == firsts.count("B")
