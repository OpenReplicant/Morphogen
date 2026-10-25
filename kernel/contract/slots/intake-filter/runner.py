"""The intake-filter slot's own runner (set.yaml `runner:`): runs one provider's file command and its proposal entry in
child processes and judges what they answer. Prints "ok: <case id>" per passing case. Never imports the provider.

  python3 runner.py <provider directory>
"""
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from harness import KERNEL, check, meta, package  # noqa: E402

C = "urn:kk:contract:intake-filter/"
SECRET = "AKIA" + "Q3EGRTZ7OVMW2KX5"        # an AWS access key id in its documented format (not a real key)
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"

CHILD = """
import dataclasses, importlib, json, os, sys
out = os.fdopen(os.dup(1), "w")
os.dup2(2, 1)                                            # the provider's own prints go to stderr
module, name = sys.argv[1].split(":")
f = getattr(importlib.import_module(module), name)
answers = []
for cs in json.load(sys.stdin):
    r = f(cs)
    r = dataclasses.asdict(r) if dataclasses.is_dataclass(r) else dict(r)
    answers.append(r)
out.write(json.dumps(answers))
"""


def env(provider: Path) -> dict:
    return {**os.environ, "PYTHONPATH": os.pathsep.join(p for p in (str(KERNEL / "src"), str(provider), os.environ.get("PYTHONPATH")) if p)}


def claim(value: str, quote: str | None = None, qualifier: str | None = None) -> dict:
    return {"op": "add_claim", "subject": "urn:x:s", "predicate": LABEL, "object": {"value": {"@value": value}},
            **({"qualifiers": {"urn:x:note": qualifier}} if qualifier else {}),
            "evidence_type": "extracted" if quote else "testimony",
            "references": [{"source_uri": "urn:x:src", **({"quote": quote} if quote else {})}]}


def proposal(*ops) -> dict:
    return {"idempotency_key": "contract", "attributed_to": "urn:kk:agent:contract", "target_scope": "urn:kk:scope:default",
            "ops": list(ops)}


def main(provider: Path) -> int:
    ok = True
    pkg = package(provider)
    with tempfile.TemporaryDirectory() as d:
        root = Path(d, "repo")
        root.mkdir()
        (root / "clean.txt").write_text("the pump runs at 40 litres per minute\n")
        (root / "other.txt").write_text("nothing to see\n")
        (root / "leak.txt").write_text("first line\naws_access_key_id = " + SECRET + "\n")
        Path(d, "outside.txt").write_text("aws_access_key_id = " + SECRET + "\n")

        def files(paths):
            return subprocess.run([sys.executable, "-m", pkg, "--repo", str(root)], input=json.dumps(paths), cwd=provider,
                                  capture_output=True, text=True, env=env(provider), timeout=300)
        out = files(["clean.txt", "other.txt"])
        got = json.loads(out.stdout) if out.returncode == 0 else {}
        ok &= check(sorted(got.get("paths", [])) == ["clean.txt", "other.txt"] and not got.get("blocked"),
                    C + "files-clean-pass", out.stdout[-300:] + out.stderr[-300:])
        out = files(["clean.txt", "leak.txt"])
        got = json.loads(out.stdout) if out.returncode == 0 else {}
        blocked = got.get("blocked") or []
        ok &= check(got.get("paths") == ["clean.txt"] and [(b.get("path"), b.get("line")) for b in blocked] == [("leak.txt", 2)],
                    C + "files-secret-blocked", out.stdout[-300:] + out.stderr[-300:])
        ok &= check(out.returncode == 0 and SECRET not in out.stdout + out.stderr, C + "files-no-echo",
                    "the secret appears in the filter's output" if SECRET in out.stdout + out.stderr else out.stderr[-300:])
        out = files(["clean.txt", "../outside.txt"])
        ok &= check(out.returncode != 0, C + "files-outside-root", out.stdout[-300:])

    entry = meta(provider).get("entry")
    if not entry or ":" not in entry:
        print(f"FAIL: {provider}/provider.yaml names no `entry: <module>:<function>` for proposals")
        return 1
    cases = [proposal(claim("the pump runs at 40 litres per minute")),
             proposal(claim("clean"), claim("aws_access_key_id = " + SECRET)),
             proposal(claim("quoted", quote="aws_access_key_id = " + SECRET)),
             proposal(claim("noted", qualifier="aws_access_key_id = " + SECRET))]
    out = subprocess.run([sys.executable, "-c", CHILD, entry], input=json.dumps(cases), cwd=provider, capture_output=True,
                         text=True, env=env(provider), timeout=300)
    if out.returncode:
        print(out.stderr[-1500:])
        print("FAIL: the proposal entry did not answer")
        return 1
    clean, value, quote, qualifier = json.loads(out.stdout)

    def stopped(r) -> bool:
        return r.get("action") == "drop" or (r.get("action") == "transform" and SECRET not in json.dumps(r.get("change_set")))
    ok &= check(clean.get("action") == "pass" and not clean.get("change_set"), C + "proposal-clean-pass", str(clean))
    ok &= check(stopped(value), C + "proposal-secret-in-value", str(value)[:300])
    ok &= check(stopped(quote), C + "proposal-secret-in-quote", str(quote)[:300])
    ok &= check(stopped(qualifier), C + "proposal-secret-in-qualifier", str(qualifier)[:300])
    ok &= check(all(SECRET not in json.dumps(r) for r in (value, quote, qualifier)) and SECRET not in out.stderr,
                C + "proposal-no-echo", "the secret appears in an answer")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
