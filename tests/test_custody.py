import json

import pytest

from judge import custody

KEY = "k" * 40


def test_round_trip_and_refusals(tmp_path, monkeypatch):
    plain, sealed, back = tmp_path / "p", tmp_path / "s", tmp_path / "b"
    (plain / "set-a").mkdir(parents=True)
    rows = b'{"id": "c1", "input": 1, "answer": 2}\n'
    (plain / "set-a/cases.jsonl").write_bytes(rows)
    monkeypatch.setenv("K", KEY)
    custody.main(["seal", "--key-env", "K", "--plain", str(plain), "--sealed", str(sealed)])
    blob = (sealed / "set-a/cases.jsonl.sealed").read_bytes()
    assert b"answer" not in blob and b"c1" not in blob
    custody.main(["open", "--key-env", "K", "--plain", str(back), "--sealed", str(sealed)])
    assert (back / "set-a/cases.jsonl").read_bytes() == rows
    with pytest.raises(SystemExit, match="authentication"):                      # wrong key
        custody.open_bytes("w" * 40, "set-a", blob)
    with pytest.raises(SystemExit, match="not case set"):                          # renamed to another set
        custody.open_bytes(KEY, "set-b", blob)
    doc = json.loads(blob)
    doc["header"]["set"] = "set-b"                                                 # header edited to match
    with pytest.raises(SystemExit, match="authentication"):
        custody.open_bytes(KEY, "set-b", json.dumps(doc).encode())
    with pytest.raises(SystemExit, match="32"):
        custody.seal_bytes("short", "set-a", rows)
