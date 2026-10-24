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
    mine = {DCT + "isPartOf": profile}             # the catalog's word for it, as with every value below
    claim(s, DCT + "type", {"entity": f"urn:kk:component-kind:{slug(e.get('kind', 'component'))}"}, mine)
    if e.get("version"):
        claim(s, OWL_VERSION, lit(str(e["version"])), mine)
    if e.get("licence"):
        claim(s, DCT + "license", lit(str(e["licence"])), mine)
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


FACTS = {DCT + "license": "licence", OWL_VERSION: "version", DCT + "type": "kind"}


def group(rows) -> dict[tuple[str, str], dict]:
    """Catalog lookup's claims (id, subject, predicate, object_entity, object_value, qualifiers), per (entry,
    catalog): every value of each property with the claim it came from, the claims of the rules' verdicts, whether an
    enforced rule refuses the entry, and the claim that it is in the catalog. Only a value the catalog itself gave
    counts (qualified dcterms:isPartOf the catalog, R5-30): two catalogs may disagree about one provider."""
    out: dict[tuple[str, str], dict] = {}

    def at(subj, profile):
        return out.setdefault((subj, profile), {"properties": {}, "rules": [], "refused": False, "member": None})
    for i, subj, pred, ent, val, q in sorted(rows, key=lambda r: str(r[0])):
        q = q or {}
        v = _value({"object_value": val}) if val is not None else None
        if pred == DCT + "isPartOf" and (ent or "").startswith("urn:kk:catalog:"):
            at(subj, ent)["member"] = i
            continue
        profile = q.get(DCT + "isPartOf")
        if not profile:
            continue                                       # unqualified (recorded before T20): superseded by the next search
        if pred == VALUE and NAME in q:
            e = at(subj, profile)
            if q[NAME].startswith("rule:"):
                e["rules"].append(i)
                e["refused"] |= str(v).startswith("fails") and str(v).endswith("(enforced)")
            else:
                e["properties"].setdefault(q[NAME], []).append((v, i))
        elif pred in FACTS:
            v = (ent or "").removeprefix("urn:kk:component-kind:") if pred == DCT + "type" else v
            at(subj, profile)["properties"].setdefault(FACTS[pred], []).append((v, i))
    return {k: e for k, e in out.items() if e["member"]}


def entries(cur) -> dict[tuple[str, str], dict]:
    cur.execute("""select id::text, subject, predicate, object_entity, object_value, qualifiers from api.claims
                   where attributed_to = %s and status <> 'deprecated' and redacted_at is null
                     and predicate = any(%s)""", (AGENT, [VALUE, DCT + "isPartOf", *FACTS]))
    return group(cur.fetchall())


def _scope(cur, ids: list[str]) -> str | None:
    """The most restrictive scope of the premises (invariant 3), or None when they are in two restricted scopes."""
    cur.execute("select distinct scope from api.claims where id = any(%s::uuid[])", (ids,))
    scopes = {r[0] for r in cur.fetchall()} - {SCOPE}
    return SCOPE if not scopes else (scopes.pop() if len(scopes) == 1 else None)


def match_needs(conn) -> dict:
    """One pass of requirement matching over the record (T20): each need against each recorded entry, per catalog.
    An entry every requirement holds for, and no enforced rule refuses, is offered: `<entry> kkt:fulfills <need>`,
    inferred from the requirement claims, the property claims that met them, the rules' verdicts and the entry's
    membership of the catalog, in the most restrictive of their scopes. A changed match supersedes the earlier
    offer; an entry no longer matched has it retracted. Nothing is read from a catalog here, and no model judges a
    match. A run is opened only when there is something to submit."""
    report: dict[str, list] = {}
    with conn.cursor() as cur:
        wanted, found = needs(cur), entries(cur)
        todo = []
        for need, reqs in sorted(wanted.items()):
            report[need] = []
            for (subj, profile), e in sorted(found.items()):
                ok, results = match(reqs, {"properties": e["properties"]})
                prefix = f"match:{profile}|{subj}|{need}|"
                if ok and not e["refused"]:
                    premises = sorted({r["id"] for r in reqs} | {c for _, _, _, c in results} | set(e["rules"]) | {e["member"]})
                    key = prefix + hashlib.sha256(json.dumps(premises).encode()).hexdigest()[:12]
                    scope = _scope(cur, premises)
                    if scope is None:
                        report[need].append({"entry": subj, "catalog": profile, "none": "its premises are in two restricted scopes"})
                        continue
                    ops = [{"op": "add_claim", "subject": subj, "predicate": KKT + "fulfills", "object": {"entity": need},
                            "evidence_type": "inferred", "derived_from": premises}]
                    report[need].append({"entry": subj, "catalog": profile, "why": [why for _, _, why, _ in results]})
                else:
                    ops, key, scope = [], None, None
                old = prior(cur, AGENT, prefix, key or "")
                cur.execute("select 1 from api.change_sets where idempotency_key = %s", (key,))
                if (key and cur.fetchone() and not old) or (not key and not old):
                    continue                               # offered already, or nothing to offer or withdraw
                if not key:                                # no longer matched: the offer is withdrawn
                    key = prefix + "none:" + hashlib.sha256(json.dumps(sorted(str(c["id"]) for c in old)).encode()).hexdigest()[:12]
                    cur.execute("select scope from api.claims where id = %s", (old[0]["id"],))
                    scope = cur.fetchone()[0]
                cs = {"idempotency_key": key, "attributed_to": AGENT, "target_scope": scope, "ops": ops}
                supersede(cs, old)
                todo.append((need, subj, profile, cs))
        if todo:
            with run(cur, MODULE, {"match": sorted(wanted)}) as (run_id, outputs):
                for need, subj, profile, cs in todo:
                    cid = str(submit(cur, cs, run_id)["id"])
                    for r in report[need]:
                        if r["entry"] == subj and r["catalog"] == profile:
                            r["change_set"] = cid
                outputs.update(submitted=len(todo))
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
    def step(c):
        out = {"requests": one_pass(c, intent)}
        try:
            out["needs"] = match_needs(c)
        except Exception as err:                         # a failed match must not stop build requests being answered
            c.rollback()
            out["needs"] = {"error": str(err)[:300]}
        print(json.dumps(out, default=str), flush=True)
    if a.once:
        step(conn)
        return 0
    follow(conn, step, wake=lambda e: bool({DCT + "type", VALUE} & set(e["predicates"] or [])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
