import copy
import json
from pathlib import Path

import pytest

from judge import schemas, verdict

ROOT = Path(__file__).resolve().parent.parent
CARD = json.loads((ROOT / "examples/card.json").read_text())
POLICY = json.loads((ROOT / "examples/policy.json").read_text())


def test_examples_are_valid():
    assert schemas.errors("card", CARD) == []
    assert schemas.errors("policy", POLICY) == []
    assert schemas.errors("verdict", json.loads((ROOT / "examples/verdict.json").read_text())) == []


@pytest.mark.parametrize("change", [
    lambda c: c.pop("intent"),
    lambda c: c.update(intent="two\nlines of intent here"),
    lambda c: c.update(scope=[]),
    lambda c: c.update(scope=["/etc/passwd"]),
    lambda c: c.update(scope=["topwords/../tests/x.py"]),
    lambda c: c.update(scope=["topwords\\x.py"]),
    lambda c: c["cases"].update(inline=[{"input": "a", "answer": "a"}]),   # cases by reference only
    lambda c: c["kpis"][0].update(source="reported"),                    # no self-reported KPIs
    lambda c: c["kpis"][0].update(floor=-1),
    lambda c: c["kpis"][0].update(role="maybe"),
    lambda c: c.update(extra=1),
    lambda c: c.update(network=["*.example.com"]),
])
def test_bad_cards_are_invalid(change):
    c = copy.deepcopy(CARD)
    change(c)
    assert schemas.errors("card", c)


def test_strict_parse_refuses_duplicate_keys_and_nan():
    with pytest.raises(schemas.Invalid):
        schemas.loads_strict('{"floor": 0.1, "floor": 0}')
    with pytest.raises(schemas.Invalid):
        schemas.loads_strict('{"floor": NaN}')


def test_canonical_hash_ignores_key_order_and_whitespace():
    assert schemas.sha256(CARD) == schemas.sha256(json.loads(json.dumps(CARD, indent=4, sort_keys=False)[::1]))
    other = copy.deepcopy(CARD)
    other["kpis"][1]["floor"] = 0.6
    assert schemas.sha256(other) != schemas.sha256(CARD)


def test_verdict_without_required_fields_is_invalid():
    v = json.loads((ROOT / "examples/verdict.json").read_text())
    for key in ("decision", "card_sha256", "kpis", "seed"):
        bad = dict(v)
        bad.pop(key)
        assert schemas.errors("verdict", bad), key
    assert schemas.errors("verdict", {**v, "decision": "maybe"})


def test_example_verdict_is_what_the_judge_writes():
    ids = [f"easy-{i}" for i in range(10)] + [f"mixed-{i}" for i in range(10)]
    measured = {
        "base": {"accuracy": {i: float(i.startswith("easy")) for i in ids}, "wall_seconds": {i: 0.02 for i in ids}},
        "candidate": {"accuracy": {i: 1.0 for i in ids}, "wall_seconds": {i: 0.02 for i in ids}},
    }
    v = verdict.decide(repository="owner/toy", base="a" * 40, candidate="b" * 40, judge="a" * 40, card=CARD,
                       policy=POLICY, case_ids=ids, served=1, measured=measured,
                       correct={i: True for i in ids}, seed=7)
    assert v["decision"] == "pass", v["reason"]
    v["issued_at"] = "2026-11-17T00:00:00Z"
    expected = json.loads((ROOT / "examples/verdict.json").read_text())
    assert v == expected
