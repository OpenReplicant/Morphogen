"""An unjudged change goes through the trusted stage with no cases and no runs, and comes out as a
schema-valid verdict that says it was not judged."""

import json
from pathlib import Path

from judge import schemas, score

TOY = Path(__file__).resolve().parent.parent / "e2e/toy"


def run(tmp_path, refused):
    adm = tmp_path / "adm.json"
    adm.write_text(json.dumps({"card": None, "refused": refused, "judged": False}))
    out = tmp_path / "v.json"
    score.main(["--base-checkout", str(TOY), "--cases-dir", str(tmp_path / "absent"), "--base-run",
                str(tmp_path / "none.jsonl"), "--candidate-run", str(tmp_path / "none.jsonl"), "--admission", str(adm),
                "--served", "0", "--repository", "o/r", "--base-sha", "a" * 40, "--head-sha", "b" * 40, "--out", str(out)])
    return schemas.check("verdict", json.loads(out.read_text()))


def test_unjudged_pass(tmp_path):
    v = run(tmp_path, [])
    assert (v["decision"], v["judged"], v["cases"]["served"]) == ("pass", False, 0)


def test_unjudged_refusal(tmp_path):
    v = run(tmp_path, ["not judged, ...: .github/workflows/forge.yml: is protected"])
    assert (v["decision"], v["judged"]) == ("refuse", False)
