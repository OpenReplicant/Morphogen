"""Catalog lookup (R5-30): searches the configured component sets (catalogs.py) and records what it finds.

  python3 -m registry_lookup search CATALOG [--terms WORD ...] [--slot SLOT] [--kind KIND]
      search one catalog for anyone (a person, the design agent, a planner) and record what is found
  python3 -m registry_lookup match
      match every recorded need against every recorded entry (T20) and offer what holds
  python3 -m registry_lookup [--once]
      a service: each build request the planner makes is also answered from the provider catalogs, and needs
      are matched

What is found is recorded, deterministic and referenced by the catalog (its file, or the source it read): the
catalog a `kkt:Profile`; each entry (a Morphogen provider keeps its own IRI, other entries are
urn:kk:component:<catalog>:<id>) with its label, `dcterms:isPartOf` the catalog, kind, version, licence,
source, description, properties, and each rule's verdict (a `kkt:propertyValue` named `rule:<name>`). An entry is
not typed `kkt:NodeType`: that type defines a kind of thing, which the store sends to a person (setting
review_types), as the self-encoder leaves providers untyped; membership of the catalog and the entry's kind say
what it is. For a
build request, an entry no enforced rule refuses is offered: `<entry> kkt:fulfills urn:kk:slot:<slot>`, inferred
from the request. An offered provider whose content is pinned becomes a candidate as the builder's do: copied
into intent/experiments/<id>/ (regular files only), checked as a candidate of the slot (morphogen.experiments),
committed, and recorded (`<provider> rdfs:label`, `<provider> dcterms:source <request>`, referenced by the
experiment directory and its content hash), so the sandbox measures it. An unpinned one is recorded and offered,
never run. A request is answered once.
A need (T20) is any subject with requirements: `<need> kkt:propertyValue "<value>"` qualified by kkt:propertyName and
kkt:constraint (requirements.py). Matching reads only the record: each entry's properties as recorded per catalog,
compared deterministically; an entry is offered (`kkt:fulfills <need>`, derived from the requirement and property
claims) only when every requirement holds; a property it does not state fails. Word search stays for people.
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
from .requirements import match

MODULE = "urn:kk:module:registry-lookup"
AGENT = "urn:kk:agent:registry-lookup"
SCOPE = "urn:kk:scope:default"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
OWL_VERSION = "http://www.w3.org/2002/07/owl#versionInfo"
DCT = "http://purl.org/dc/terms/"
KKT = "https://w3id.org/knowledge-kernel/tosca#"
VALUE, NAME, CONSTRAINT = KKT + "propertyValue", KKT + "propertyName", KKT + "constraint"
RETRIES = 3
COMMITTER = {"GIT_AUTHOR_NAME": "Morphogen catalog lookup", "GIT_AUTHOR_EMAIL": "registry-lookup@morphogen.invalid",
             "GIT_COMMITTER_NAME": "Morphogen catalog lookup", "GIT_COMMITTER_EMAIL": "registry-lookup@morphogen.invalid"}


def slug(x) -> str:
    return re.sub(r"[^a-z0-9._-]+", "-", str(x).lower()).strip("-") or "x"


def subject(e: dict) -> str:
    if e.get("adapter") == "providers" and str(e.get("id", "")).startswith("urn:kk:provider:"):
        return e["id"]
    return f"urn:kk:component:{slug(e['catalog'])}:{slug(e['id'])}" + (f":{slug(e['version'])}" if e.get("version") else "")


def reference(cat: dict, e: dict) -> dict:
    """What the facts were read from: the API URL or repository fetched, else the catalog file (never a URL the
    entry merely names: that is its dcterms:source)."""
    f = cat["file"]
    rel = f.relative_to(ROOT) if f.is_relative_to(ROOT) else f
    src = str(e.get("read_from") or "")
    return {"source_uri": src if re.match(r"^https?:", src) else f"file:{rel}"}


def ops_for(cat: dict, e: dict, v: dict) -> list[dict]:
    s, ref = subject(e), reference(cat, e)
    out = []

    def claim(subj, p, o, q=None):
        c = {"op": "add_claim", "subject": subj, "predicate": p, "object": o, "evidence_type": "deterministic", "references": [ref]}
        if q:
            c["qualifiers"] = q
        out.append(c)
    lit = lambda x: {"value": {"@value": x}}  # noqa: E731
    profile = f"urn:kk:catalog:{slug(cat['name'])}"
    # every value is qualified by the catalog that gave it: two catalogs may say different things of one provider
    prop = lambda name: {KKT + "propertyName": name, DCT + "isPartOf": profile}  # noqa: E731
    claim(profile, RDF_TYPE, {"entity": KKT + "Profile"})
    claim(profile, LABEL, lit(str(cat.get("label") or cat["name"])))
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
    for slot in sorted(e.get("slots") or []):
        claim(s, KKT + "propertyValue", lit(str(slot)), prop("slot"))
    for name, r in sorted(v.items()):
        claim(s, KKT + "propertyValue", lit(f"{'ok' if r['ok'] else 'fails'}: {r['why']}" + (" (enforced)" if r["enforced"] else "")),
              prop(f"rule:{name}"))
    return out


def offer(cur, run_id: str, cat: dict, e: dict, request: str, need: str, premises: list[str]) -> str:
    """The offer, one change set per request: `<entry> kkt:fulfills <need>`, inferred from the request's claims and
    referenced by what was read (which slots the entry says it fills). Another request's offer is another claim,
    so withdrawing one request undermines only its own (truth maintenance)."""
    op = {"op": "add_claim", "subject": subject(e), "predicate": KKT + "fulfills", "object": {"entity": need},
          "evidence_type": "inferred", "derived_from": sorted(premises), "references": [reference(cat, e)]}
    cs = {"idempotency_key": f"offer:{cat['name']}|{subject(e)}|{request}", "attributed_to": AGENT, "target_scope": SCOPE,
          "ops": [op]}
    return str(submit(cur, cs, run_id)["id"])


def record(cur, run_id: str, cat: dict, e: dict, v: dict) -> str:
    """One change set per entry and catalog: the same facts again are a no-op; changed facts supersede them."""
    ops = ops_for(cat, e, v)
    digest = hashlib.sha256(json.dumps(ops, sort_keys=True).encode()).hexdigest()[:16]
    prefix = f"catalog:{cat['name']}|{subject(e)}|"
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


def _id(d: Path) -> str | None:
    try:
        return str((yaml.safe_load((d / "provider.yaml").read_text()) or {}).get("id"))
    except (OSError, yaml.YAMLError, AttributeError):
        return None


def candidate(cur, run_id: str, intent: Path, r: dict, slot: str, e: dict) -> dict:
    """An offered, pinned provider -> an experiment the sandbox measures, recorded as the builder records its own."""
    inc = provider_dir(r["target"])
    if inc is None:
        raise ValueError(f"no provider directory for {r['target']}")
    exp_id = experiment_id(f"{r['iri']}|{e['id']}")
    exp = intent / "experiments" / exp_id
    if exp.exists():
        raise ValueError(f"{exp_id} exists already")
    if any(_id(d) == e["id"] for x in (intent / "experiments").glob("x*") if x.is_dir() for d in x.iterdir() if d.is_dir()):
        raise ValueError(f"{e['id']} is already a candidate in an experiment: one directory per provider id")
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
    res = submit(cur, {"idempotency_key": f"candidate:{meta['id']}|{e['sha256'][:16]}|{exp_id}", "attributed_to": AGENT,
                       "target_scope": SCOPE, "ops": [claim(LABEL, {"value": {"@value": meta.get("name", meta["id"])}}),
                                                       claim(DCT + "source", {"entity": r["iri"]})]}, run_id)
    return {"experiment": exp_id, "candidate": meta["id"], "commit": sha, "candidate_change_set": str(res["id"])}


def one_pass(conn, intent: Path) -> dict:
    report = {}
    cats = {n: c for n, c in catalogs.load(intent).items() if c.get("kind") == "providers"}
    with conn.cursor() as cur:
        # answered once: a succeeded run; a failed one (a network or git error) is retried, up to RETRIES times
        cur.execute("""select info->>'request', count(*) filter (where status = 'succeeded'), count(*) filter (where status = 'failed')
                       from kernel.run where agent = %s and info ? 'request' group by 1""", (AGENT,))
        tried = {x[0] for x in cur.fetchall() if x[1] or x[2] >= RETRIES}
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
                                     "change_set": record(cur, run_id, cat, e, v)}
                                if a["offered"]:
                                    a["offer_change_set"] = offer(cur, run_id, cat, e, r["iri"], r["slot"], r["claims"])
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


def _value(c: dict):
    v = c["object_value"]
    return v.get("@value") if isinstance(v, dict) else v


def needs(cur) -> dict[str, list[dict]]:
    """Every need in the record: its requirements, each `<need> kkt:propertyValue "<value>"` qualified by
    kkt:propertyName and kkt:constraint (current claims only)."""
    cur.execute("""select id::text, subject, object_value, qualifiers from api.claims
                   where predicate = %s and qualifiers ? %s and qualifiers ? %s and status <> 'deprecated'
                     and redacted_at is null order by subject, id""", (VALUE, NAME, CONSTRAINT))
    out: dict[str, list[dict]] = {}
    for i, subj, val, q in cur.fetchall():
        out.setdefault(subj, []).append({"id": i, "name": q[NAME], "constraint": q[CONSTRAINT],
                                         "value": _value({"object_value": val})})
    return out


def entries(cur) -> dict[tuple[str, str], dict]:
    """What catalog lookup recorded, per (entry, catalog): its properties as read from the record, each with the
    claim it came from, and whether an enforced rule refuses it. Values are the catalog's own (R5-30)."""
    cur.execute("""select id::text, subject, predicate, object_entity, object_value, qualifiers from api.claims
                   where attributed_to = %s and status <> 'deprecated' and redacted_at is null
                     and predicate = any(%s)""", (AGENT, [VALUE, DCT + "license", OWL_VERSION, DCT + "type", DCT + "isPartOf"]))
    rows = cur.fetchall()
    part = {}
    for i, subj, pred, ent, val, q in rows:
        if pred == DCT + "isPartOf" and (ent or "").startswith("urn:kk:catalog:"):
            part.setdefault(subj, []).append(ent)
    out: dict[tuple[str, str], dict] = {}
    for i, subj, pred, ent, val, q in rows:
        v = _value({"object_value": val}) if val is not None else None
        q = q or {}
        if pred == VALUE and q.get(DCT + "isPartOf") and NAME in q:
            e = out.setdefault((subj, q[DCT + "isPartOf"]), {"properties": {}, "claims": {}, "refused": False})
            if q[NAME].startswith("rule:"):
                e["refused"] |= str(v).startswith("fails") and str(v).endswith("(enforced)")
            else:
                e["properties"][q[NAME]], e["claims"][q[NAME]] = v, i
        elif pred in (DCT + "license", OWL_VERSION, DCT + "type"):
            name = {DCT + "license": "licence", OWL_VERSION: "version", DCT + "type": "kind"}[pred]
            v = (ent or "").removeprefix("urn:kk:component-kind:") if pred == DCT + "type" else v
            for profile in part.get(subj, []):         # an entry's own facts hold in each catalog that lists it
                e = out.setdefault((subj, profile), {"properties": {}, "claims": {}, "refused": False})
                e["properties"].setdefault(name, v)
                e["claims"].setdefault(name, i)
    return out


def match_needs(conn) -> dict:
    """One pass of requirement matching over the record (T20): each need against each recorded entry, per catalog.
    An entry every requirement holds for, and no enforced rule refuses, is offered: `<entry> kkt:fulfills <need>`,
    inferred from the requirement claims and the property claims compared. Nothing is read from a catalog here,
    and nothing a model said is used."""
    report = {}
    with conn.cursor() as cur:
        wanted, found = needs(cur), entries(cur)
        if not wanted:
            return report
        with run(cur, MODULE, {"match": sorted(wanted)}) as (run_id, outputs):
            for need, reqs in sorted(wanted.items()):
                got = []
                for (subj, profile), e in sorted(found.items()):
                    ok, results = match(reqs, {"properties": e["properties"]})
                    if not ok or e["refused"]:
                        continue
                    premises = sorted({r["id"] for r in reqs} | {e["claims"][r["name"]] for r in reqs})
                    digest = hashlib.sha256(json.dumps(premises).encode()).hexdigest()[:12]
                    op = {"op": "add_claim", "subject": subj, "predicate": KKT + "fulfills", "object": {"entity": need},
                          "evidence_type": "inferred", "derived_from": premises}
                    cs = {"idempotency_key": f"match:{profile}|{subj}|{need}|{digest}", "attributed_to": AGENT,
                          "target_scope": SCOPE, "ops": [op]}
                    got.append({"entry": subj, "catalog": profile, "change_set": str(submit(cur, cs, run_id)["id"]),
                                "why": [why for _, _, why in results]})
                report[need] = got
            outputs.update(offers=sum(len(x) for x in report.values()))
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
    sub.add_parser("match", help="match every recorded need against every recorded entry, and offer what holds")
    a = ap.parse_args(argv)
    intent = Path(os.environ.get("KK_INTENT_DIR", ROOT / "morphogen" / "intent")).resolve()
    conn = connect(os.environ.get("KK_ROLE", "kkm_registry_lookup"))
    if a.cmd == "search":
        out = search(conn, intent, a.catalog, {k: v for k, v in {"terms": a.terms, "slot": a.slot, "kind": a.kind}.items() if v}
                     | ({"min_age_days": a.min_age_days} if a.min_age_days is not None else {}))
        print(json.dumps(out, default=str))
        return 1 if "refused" in out else 0
    if a.cmd == "match":
        print(json.dumps(match_needs(conn), default=str))
        return 0
    step = lambda c: print(json.dumps({"requests": one_pass(c, intent), "needs": match_needs(c)}, default=str), flush=True)  # noqa: E731
    if a.once:
        step(conn)
        return 0
    follow(conn, step, wake=lambda e: bool({DCT + "type", VALUE} & set(e["predicates"] or [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
