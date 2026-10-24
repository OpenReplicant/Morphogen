"""Catalog lookup (R5-30): searches the configured component sets (catalogs.py) and records what it finds.

  python3 -m registry_lookup search CATALOG [--terms WORD ...] [--slot SLOT] [--kind KIND]
      search one catalog for anyone (a person, the design agent, a planner) and record what is found
  python3 -m registry_lookup [--once]
      a service: each build request the planner makes is also answered from the provider catalogs

What is found is recorded, deterministic and referenced by the catalog (its file, or the source it read): the
catalog a `kkt:Profile`; each entry a `kkt:NodeType` (a Morphogen provider keeps its own IRI, other entries are
urn:kk:component:<catalog>:<id>) with its label, `dcterms:isPartOf` the catalog, kind, version, licence,
source, description, properties, and each rule's verdict (a `kkt:propertyValue` named `rule:<name>`). For a
build request, an entry no enforced rule refuses is offered: `<entry> kkt:fulfills urn:kk:slot:<slot>`, inferred
from the request. An offered provider whose content is pinned becomes a candidate as the builder's do: copied
into intent/experiments/<id>/ (regular files only), checked as a candidate of the slot (morphogen.experiments),
committed, and recorded (`<provider> rdfs:label`, `<provider> dcterms:source <request>`, referenced by the
experiment directory and its content hash), so the sandbox measures it. An unpinned one is recorded and offered,
never run. A request is answered once.
Env: DATABASE_URL (a login that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_registry_lookup), KK_INTENT_DIR
(default morphogen/intent), KK_SWEEP_SECONDS.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

from kk.changes import prior, supersede
from kk.lib import connect, follow, run, submit
from morphogen import confine
from morphogen.experiments import ROOT, build_requests, check_candidate, experiment_id, provider_dir, tree_hash

from . import catalogs

MODULE = "urn:kk:module:registry-lookup"
AGENT = "urn:kk:agent:registry-lookup"
SCOPE = "urn:kk:scope:default"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
OWL_VERSION = "http://www.w3.org/2002/07/owl#versionInfo"
DCT = "http://purl.org/dc/terms/"
KKT = "https://w3id.org/knowledge-kernel/tosca#"
COMMITTER = {"GIT_AUTHOR_NAME": "Morphogen catalog lookup", "GIT_AUTHOR_EMAIL": "registry-lookup@morphogen.invalid",
             "GIT_COMMITTER_NAME": "Morphogen catalog lookup", "GIT_COMMITTER_EMAIL": "registry-lookup@morphogen.invalid"}


def slug(x) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", str(x).lower()).strip("-") or "x"


def subject(e: dict) -> str:
    if e.get("kind") == "provider" and str(e.get("id", "")).startswith("urn:kk:provider:"):
        return e["id"]
    return f"urn:kk:component:{slug(e['catalog'])}:{slug(e['id'])}" + (f":{slug(e['version'])}" if e.get("version") else "")


def reference(cat: dict, e: dict) -> dict:
    f = cat["file"]
    rel = f.relative_to(ROOT) if f.is_relative_to(ROOT) else f
    src = str(e.get("source") or "")
    return {"source_uri": src if re.match(r"^(https?|file):", src) else f"file:{rel}"}


def ops_for(cat: dict, e: dict, v: dict, need: str | None, premises: list[str]) -> list[dict]:
    s, ref = subject(e), reference(cat, e)
    out = []

    def claim(subj, p, o, q=None):
        c = {"op": "add_claim", "subject": subj, "predicate": p, "object": o, "evidence_type": "deterministic", "references": [ref]}
        if q:
            c["qualifiers"] = q
        out.append(c)
    lit = lambda x: {"value": {"@value": x}}  # noqa: E731
    prop = lambda name: {KKT + "propertyName": name}  # noqa: E731
    profile = f"urn:kk:catalog:{slug(cat['name'])}"
    claim(profile, RDF_TYPE, {"entity": KKT + "Profile"})
    claim(profile, LABEL, lit(str(cat.get("label") or cat["name"])))
    claim(s, RDF_TYPE, {"entity": KKT + "NodeType"})
    claim(s, LABEL, lit(str(e.get("label") or e["id"])))
    claim(s, DCT + "isPartOf", {"entity": profile})
    claim(s, DCT + "type", {"entity": f"urn:kk:component-kind:{slug(e.get('kind', 'component'))}"})
    if e.get("version"):
        claim(s, OWL_VERSION, lit(str(e["version"])))
    if e.get("licence"):
        claim(s, DCT + "license", lit(str(e["licence"])))
    if e.get("description"):
        claim(s, DCT + "description", lit(str(e["description"])[:2000]))
    if re.match(r"^https?://", str(e.get("source") or "")):
        claim(s, DCT + "source", {"entity": str(e["source"]).split("#")[0]})
    for k, val in sorted((e.get("properties") or {}).items()):
        claim(s, KKT + "propertyValue", lit(str(val)), prop(str(k)))
    if e.get("sha256"):
        claim(s, KKT + "propertyValue", lit(str(e["sha256"])), prop("sha256"))
    for name, r in sorted(v.items()):
        claim(s, KKT + "propertyValue", lit(f"{'ok' if r['ok'] else 'fails'}: {r['why']}" + (" (enforced)" if r["enforced"] else "")),
              prop(f"rule:{name}"))
    if need and catalogs.offer(v):
        out.append({"op": "add_claim", "subject": s, "predicate": KKT + "fulfills", "object": {"entity": need},
                    "evidence_type": "inferred", "derived_from": premises})
    return out


def record(cur, run_id: str, cat: dict, e: dict, v: dict, need: str | None = None, premises: list[str] = ()) -> str:
    """One change set per entry (and need): the same facts again are a no-op; changed facts supersede them."""
    ops = ops_for(cat, e, v, need, list(premises))
    digest = hashlib.sha256(json.dumps(ops, sort_keys=True).encode()).hexdigest()[:16]
    prefix = f"catalog:{cat['name']}|{subject(e)}|{need or ''}|"
    cs = {"idempotency_key": prefix + digest, "attributed_to": AGENT, "target_scope": SCOPE, "ops": ops}
    old = prior(cur, AGENT, prefix, cs["idempotency_key"])
    if old:
        supersede(cs, old)
    return str(submit(cur, cs, run_id)["id"])


def search(conn, intent: Path, name: str, query: dict) -> dict:
    cats = catalogs.load(intent)
    if name not in cats:
        return {"refused": f"no catalog {name!r} in {intent / 'catalogs'}"}
    cat = cats[name]
    rules = catalogs.rules(intent, cat)
    opts = catalogs.settings(intent, cat, query)
    found = catalogs.search(cat, {**query, "min_age_days": opts.get("min_age_days")})[: int(opts.get("max_results", 20))]
    out = []
    with conn.cursor() as cur, run(cur, MODULE, {"catalog": name, "query": query}) as (run_id, outputs):
        for e in found:
            v = catalogs.verdicts(e, rules)
            out.append({"entry": subject(e), "verdicts": v, "change_set": record(cur, run_id, cat, e, v)})
        outputs.update(found=len(out))
    return {"catalog": name, "found": out}


def commit(intent: Path, exp: Path, msg: str) -> str:
    git = lambda *a: subprocess.run(["git", "-C", str(intent), *a], check=True, capture_output=True, text=True,  # noqa: E731
                                    env={**os.environ, **COMMITTER}).stdout.strip()
    rel = str(exp.relative_to(intent))
    git("add", "--", rel)
    git("commit", "-q", "-m", msg, "--", rel)
    return git("rev-parse", "HEAD")


def candidate(cur, run_id: str, intent: Path, r: dict, slot: str, e: dict) -> dict:
    """An offered, pinned provider -> an experiment the sandbox measures, recorded as the builder records its own."""
    inc = provider_dir(r["target"])
    if inc is None:
        raise ValueError(f"no provider directory for {r['target']}")
    exp_id = experiment_id(f"{r['iri']}|{e['id']}")
    exp = intent / "experiments" / exp_id
    if exp.exists():
        raise ValueError(f"{exp_id} exists already")
    exp.mkdir(parents=True)
    try:
        work = exp / slug(e["id"].removeprefix("urn:kk:provider:"))
        confine.copy_tree(Path(e["path"]), work)          # regular files only, fixed modes; a link is refused
        if tree_hash(work) != e["sha256"]:
            raise ValueError("the copied provider is not the content the catalog pinned")
        meta = check_candidate(work, slot, yaml.safe_load((inc / "provider.yaml").read_text())["id"], inc)
        (exp / "experiment.yaml").write_text(yaml.safe_dump(
            {"slot": slot, "incumbent": str(inc.relative_to(ROOT)), "candidate": work.name, "request": r["iri"],
             "strategy": "catalog", "catalog": e["catalog"], "source": e.get("source")}, sort_keys=False))
        sha = commit(intent, exp, f"request:{r['iri']} experiment:{exp_id}\n\nCandidate {meta['id']} for the {slot} slot, "
                                  f"from the catalog {e['catalog']} ({e.get('source')}).\n")
    except Exception:
        shutil.rmtree(exp, ignore_errors=True)
        raise
    rel = exp.relative_to(intent.parent) if exp.is_relative_to(intent.parent) else exp
    ref = [{"source_uri": f"file:{rel}/{work.name}#sha256={e['sha256']}"}]
    claim = lambda p, o: {"op": "add_claim", "subject": meta["id"], "predicate": p, "object": o,  # noqa: E731
                          "evidence_type": "deterministic", "references": ref}
    res = submit(cur, {"idempotency_key": f"candidate:{meta['id']}|{e['sha256'][:16]}|catalog", "attributed_to": AGENT,
                       "target_scope": SCOPE, "ops": [claim(LABEL, {"value": {"@value": meta.get("name", meta["id"])}}),
                                                       claim(DCT + "source", {"entity": r["iri"]})]}, run_id)
    return {"experiment": exp_id, "candidate": meta["id"], "commit": sha, "change_set": str(res["id"])}


def one_pass(conn, intent: Path) -> dict:
    report = {}
    cats = {n: c for n, c in catalogs.load(intent).items() if c.get("kind") == "providers"}
    with conn.cursor() as cur:
        cur.execute("select distinct info->>'request' from kernel.run where agent = %s and info ? 'request'", (AGENT,))
        tried = {x[0] for x in cur.fetchall()}
        for r in build_requests(cur):
            if r["iri"] in tried or not cats:
                continue
            slot = r["slot"].removeprefix("urn:kk:slot:")
            answers = []
            try:
                with run(cur, MODULE, {"request": r["iri"], "slot": slot}, used=r["claims"]) as (run_id, outputs):
                    for name, cat in sorted(cats.items()):
                        rules = catalogs.rules(intent, cat)
                        with tempfile.TemporaryDirectory(prefix="kk-catalog-") as d:
                            opts = catalogs.settings(intent, cat, {})
                            for e in catalogs.search(cat, {"slot": slot, "min_age_days": opts.get("min_age_days")}, workdir=Path(d)):
                                if e["id"] == r["target"]:
                                    continue                     # the incumbent itself
                                v = catalogs.verdicts(e, rules)
                                a = {"catalog": name, "entry": e["id"], "offered": catalogs.offer(v),
                                     "change_set": record(cur, run_id, cat, e, v, r["slot"], r["claims"])}
                                if a["offered"] and e.get("pinned"):
                                    try:
                                        a.update(candidate(cur, run_id, intent, r, slot, e))
                                    except Exception as err:     # recorded in the run; the next entry is tried
                                        a["refused"] = str(err)[:300]
                                elif a["offered"]:
                                    a["refused"] = "not pinned: recorded and offered, never run (R5-30 d)"
                                answers.append(a)
                    outputs.update(answers=answers)
                report[r["iri"]] = {"status": "answered", "answers": answers}
            except Exception as err:                             # a failed run, recorded; go on with the next request
                report[r["iri"]] = {"status": "failed", "error": str(err)[:300]}
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Search component catalogs; answer build requests from provider catalogs.")
    ap.add_argument("--once", action="store_true", help="one pass of the service, print the result and exit")
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("search")
    s.add_argument("catalog")
    s.add_argument("--terms", nargs="*", default=[])
    s.add_argument("--slot")
    s.add_argument("--kind")
    s.add_argument("--min-age-days", type=float, help="leave out releases newer than this (0: none; default: the policy's)")
    a = ap.parse_args(argv)
    intent = Path(os.environ.get("KK_INTENT_DIR", ROOT / "morphogen" / "intent")).resolve()
    conn = connect(os.environ.get("KK_ROLE", "kkm_registry_lookup"))
    if a.cmd == "search":
        out = search(conn, intent, a.catalog, {k: v for k, v in {"terms": a.terms, "slot": a.slot, "kind": a.kind}.items() if v}
                     | ({"min_age_days": a.min_age_days} if a.min_age_days is not None else {}))
        print(json.dumps(out, default=str))
        return 1 if "refused" in out else 0
    step = lambda c: print(json.dumps(one_pass(c, intent), default=str), flush=True)  # noqa: E731
    if a.once:
        step(conn)
        return 0
    follow(conn, step, wake=lambda e: DCT + "type" in (e["predicates"] or []))
    return 0


if __name__ == "__main__":
    sys.exit(main())
