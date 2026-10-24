"""Intake filter checks (rebuild 4 M3-T4, plus R5-29): a large file is scanned in chunks and a finding keeps
its line; a proposal carrying a secret is dropped, naming the op; without gitleaks it fails closed.

  python3 kernel/providers/filter-gitleaks/tests/test_filter.py      (needs gitleaks on PATH)
"""
import os
import sys
import tempfile
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[3] / "src")]
import filter_gitleaks.__main__ as f  # noqa: E402

checks = []


def check(name, ok, detail=""):
    checks.append(bool(ok))
    print(("ok  " if ok else "FAIL"), name, detail)


# A fake key built at run time, so this file holds no secret-looking literal.
KEY = "AKIA" + "Q3EGRTZ7OVMW2KX5"
f.CHUNK, f.OVERLAP = 4096, 64
with tempfile.TemporaryDirectory() as d:
    repo = Path(d)
    rows = [f"<event n='{i}'/>\n" for i in range(3000)]
    rows[2500] = f"aws_access_key_id = {KEY}\n"
    (repo / "big.xes").write_text("".join(rows))
    (repo / "small.txt").write_text("nothing to see\n")
    (Path(d) / "copy").mkdir()
    chunks = f.split(repo / "big.xes", Path(d) / "copy" / "big.xes")
    text = "".join(rows)
    check("a large file is split into overlapping chunks that keep its suffix and cover it",
          len(chunks) > 5 and all(n.endswith(".xes") for n in chunks)
          and "".join((Path(d) / "copy" / n).read_text()[:f.CHUNK] for n in chunks) == text)
    (repo / "one.xes").write_text("<log>" + "<e/>" * 3000 + f"<x>{KEY}</x>" + "<e/>" * 3000 + "</log>")
    res = f.scan(repo, ["big.xes", "small.txt", "one.xes"])
    check("a finding in a chunk is reported at the file's own line, the file blocked",
          res["paths"] == ["small.txt"] and [(b["path"], b["line"]) for b in res["blocked"]] == [("big.xes", 2501), ("one.xes", 1)],
          res["blocked"])
    f.CHUNK = len("<log>" + "<e/>" * 3000) + 4       # the cut falls inside the key
    check("a secret across a cut is still found (chunks overlap)",
          f.scan(repo, ["one.xes"])["blocked"] == [{"path": "one.xes", "line": 1, "rule": "aws-access-token"}])
f.CHUNK, f.OVERLAP = 32 << 20, 64 << 10
cs = {"ops": [{"op": "add_claim", "subject": "urn:kk:node:shop", "object": {"value": {"@value": "fine"}}},
              {"op": "add_claim", "subject": "urn:kk:node:shop", "object": {"value": {"@value": "fine"}},
               "references": [{"source_uri": "urn:kk:message:x", "quote": f"the key is {KEY}"}]}]}
res = f.filter(cs)
check("a proposal quoting a secret is dropped, naming the rule and the op, not the secret",
      res.action == "drop" and "op 1" in res.reason and KEY not in res.reason, res)
check("a proposal with no secret passes", f.filter({"ops": cs["ops"][:1]}).action == "pass")
path = os.environ["PATH"]
os.environ["PATH"] = "/nonexistent"
try:
    f.filter(cs)
    closed = False
except (OSError, RuntimeError):
    closed = True
finally:
    os.environ["PATH"] = path
check("without gitleaks it fails closed (an error, not a pass)", closed)
with tempfile.TemporaryDirectory() as d:
    fake = Path(d, "gitleaks")
    fake.write_text("#!/bin/sh\necho broken >&2\nexit 2\n")
    fake.chmod(0o755)
    os.environ["PATH"] = f"{d}:{path}"
    try:
        f.filter(cs)
        closed = False
    except RuntimeError:
        closed = True
    finally:
        os.environ["PATH"] = path
check("when gitleaks runs and fails, it fails closed", closed)
print(f"ingest filter checks passed ({sum(checks)}/{len(checks)})" if all(checks) else "ingest filter checks FAILED")
sys.exit(0 if all(checks) else 1)
