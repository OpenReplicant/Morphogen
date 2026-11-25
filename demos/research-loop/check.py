"""Check the research loop's phase-0 records: every claim against schemas/evidence-claim.v1.json, every option's
spec.morphogen against schemas/morphogen-spec.v1.json, and the links between them.

    uv run --with jsonschema==4.26.0 --with pyyaml python -I demos/research-loop/check.py [--metasoar PATH]

With --metasoar (a local clone of OpenReplicant/MetaSoar), every quote taken from MetaSoar at a commit (a claim's
source or via, and the map's evidence annotations) is also matched against the file at that commit, whitespace
collapsed. Exits non-zero on any failure.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
METASOAR = "OpenReplicant/MetaSoar"


class Loader(yaml.SafeLoader):
    """YAML as JSON sees it: a date stays a string, as the schema's `format: date` expects."""


Loader.yaml_implicit_resolvers = {k: [(t, r) for t, r in v if t != "tag:yaml.org,2002:timestamp"]
                                  for k, v in yaml.SafeLoader.yaml_implicit_resolvers.items()}


def ref(r: str, kind: str = "component") -> str:
    k, _, rest = r.partition(":") if ":" in r else (kind, "", r)
    ns, _, name = rest.rpartition("/")
    return f"{k.lower()}:{(ns or 'default').lower()}/{name.lower()}"


def catalog() -> dict[str, dict]:
    """The demo's catalog: the root and its Location targets, by full ref."""
    out, todo = {}, [HERE / "catalog-info.yaml"]
    while todo:
        f = todo.pop()
        for e in yaml.load_all(f.read_text(), Loader):
            if e["kind"] == "Location":
                todo += [(f.parent / t).resolve() for t in e["spec"]["targets"]]
            else:
                out[ref(e["metadata"]["name"], e["kind"].lower())] = {**e, "_file": f.relative_to(HERE).as_posix()}
    return out


def flat(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--metasoar", type=Path, help="a local clone of OpenReplicant/MetaSoar, to check quotes")
    args = ap.parse_args()
    claim_schema = json.loads((ROOT / "schemas/evidence-claim.v1.json").read_text())
    spec_schema = json.loads((ROOT / "schemas/morphogen-spec.v1.json").read_text())
    Draft202012Validator.check_schema(claim_schema)
    cv = Draft202012Validator(claim_schema, format_checker=Draft202012Validator.FORMAT_CHECKER)
    sv = Draft202012Validator(spec_schema)
    errors: list[str] = []
    ents = catalog()

    def bad(where: str, msg: str) -> None:
        errors.append(f"{where}: {msg}")

    # options: spec.morphogen against the spec schema
    options = {r: e for r, e in ents.items() if e["kind"] == "Component" and e["spec"].get("lifecycle") == "candidate"}
    roles = {r for r, e in ents.items() if e["kind"] == "Component" and e["spec"].get("type") == "role"}
    for r, e in options.items():
        for err in sv.iter_errors(e["spec"].get("morphogen") or {}):
            bad(f"{e['_file']} {r}", f"spec.morphogen: {err.message}")
    print(f"options: {len(options)} against schemas/morphogen-spec.v1.json, roles: {len(roles)}")

    # claims: the schema
    files = sorted((HERE / "claims").rglob("*.yaml"))
    claims: dict[str, tuple[str, dict]] = {}
    for f in files:
        rel = f.relative_to(HERE).as_posix()
        doc = yaml.load(f.read_text(), Loader)
        errs = sorted(cv.iter_errors(doc), key=lambda x: list(x.absolute_path))
        for err in errs:
            bad(rel, f"{'/'.join(map(str, err.absolute_path)) or '(root)'}: {err.message}")
        print(f"{'ok  ' if not errs else 'FAIL'} {rel}")
        if errs:
            continue
        name = doc["metadata"]["name"]
        if name != f.stem:
            bad(rel, f"metadata.name {name} is not the file's name")
        if name in claims:
            bad(rel, f"{name} is also {claims[name][0]}")
        claims[name] = (rel, doc)

    # links
    for name, (rel, doc) in claims.items():
        s = doc["spec"]
        about, role = ref(s["about"]), ref(s["role"])
        if about not in options:
            bad(rel, f"about {s['about']} is not an option (a Component with lifecycle candidate)")
            continue
        if role not in roles:
            bad(rel, f"role {s['role']} is not a role (a Component with type role)")
        fills = options[about]["spec"]["morphogen"].get("fills") or []
        if role not in {ref(x) for x in ([fills] if isinstance(fills, str) else fills)}:
            bad(rel, f"{s['about']} does not fill {s['role']}")
        for v in (s["conditions"].get(k) or {} for k in ("engine", "dataset", "hardware")):
            if v.get("ref") and ref(v["ref"]) not in ents:
                bad(rel, f"conditions ref {v['ref']} is not in the catalog")
        for m in s["conditions"].get("models") or []:
            if m.get("ref") and ref(m["ref"]) not in ents:
                bad(rel, f"model ref {m['ref']} is not in the catalog")
        for a in s.get("assessments") or []:
            if ref(a["system"], "system") not in ents:
                bad(rel, f"system {a['system']} is not in the catalog")
            for x in a.get("against") or []:
                if ref(x) not in ents:
                    bad(rel, f"against {x} is not in the catalog")
            for x in (a.get("outcome") or {}).get("observed", []):
                if x not in claims or claims[x][1]["spec"]["source"]["kind"] != "trial":
                    bad(rel, f"observed {x} is not a trial's claim")
            for x in a.get("see_also") or []:
                if x not in claims:
                    bad(rel, f"see_also {x} is not a claim")
    for r, e in options.items():
        listed = set((e["spec"]["morphogen"].get("evaluation") or {}).get("evidence") or [])
        actual = {rel for rel, d in claims.values() if ref(d["spec"]["about"]) == r}
        for x in sorted(listed - actual):
            bad(f"{e['_file']} {r}", f"evaluation.evidence lists {x}, which is not a claim about it")
        for x in sorted(actual - listed):
            bad(f"{e['_file']} {r}", f"evaluation.evidence leaves out {x}")

    # quotes from MetaSoar at a commit
    quotes: list[tuple[str, str, str, str]] = []   # where, commit, path, quote
    for name, (rel, doc) in claims.items():
        src = doc["spec"]["source"]
        for part, q in (("source", src), ("source.via", src.get("via") or {})):
            if q.get("repository") == METASOAR and q.get("quote"):
                quotes.append((f"{rel} {part}", q["commit"], q["path"], q["quote"]))
    for r, e in ents.items():
        for line in (e["metadata"].get("annotations") or {}).get("morphogen.dev/evidence", "").splitlines():
            m = re.match(rf'\s*\w+ \| {re.escape(METASOAR)}@([0-9a-f]+):(\S+) \| "(.*)"\s*$', line)
            if m:
                quotes.append((f"{e['_file']} {r}", *m.groups()))
    if args.metasoar:
        texts: dict[tuple[str, str], str] = {}
        for where, commit, path, q in quotes:
            if (commit, path) not in texts:
                texts[commit, path] = flat(subprocess.run(["git", "-C", str(args.metasoar), "show", f"{commit}:{path}"],
                                                          capture_output=True, text=True, check=True).stdout)
            if flat(q) not in texts[commit, path]:
                bad(where, f"quote not found in {METASOAR}@{commit[:7]}:{path}: {q[:60]}...")
        print(f"quotes: {len(quotes)} matched against {METASOAR} at their commits")
    else:
        print(f"quotes: {len(quotes)} not checked (no --metasoar)")

    trial = sum(d["spec"]["source"]["kind"] in ("trial", "probe") for _, d in claims.values())
    status: dict[str, int] = {}
    for _, d in claims.values():
        for a in d["spec"].get("assessments") or []:
            status[a["status"]] = status.get(a["status"], 0) + 1
    print(f"claims: {len(claims)} ({len(claims) - trial} from papers, {trial} our own observations); "
          f"statuses for system:default/metasoar: {dict(sorted(status.items()))}")
    for e in errors:
        print("ERROR", e)
    print("FAILED" if errors else "all checks pass")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
