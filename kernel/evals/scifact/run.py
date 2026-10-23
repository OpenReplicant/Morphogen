"""SciFact retrieval on the kernel (rebuild 4 eval/scifact stage 1, D-59, D-60): the recall slot's floor.

  python kernel/evals/scifact/run.py fetch       download SciFact and its BEIR split, checked by sha256
  python kernel/evals/scifact/run.py setup DB    install the record, validator and recall-bm25 into DB, encode
                                                 the 5,183 abstracts (as rebuild 4's paper encoder did), validate
                                                 them through validator-shacl and build the BM25 index
  python kernel/evals/scifact/run.py retrieval DB
                                                 the 300 dev claims through kk.recall as an agent, scored as BEIR
                                                 does (nDCG@10, recall within the top 200 claims), with latency

Rebuild 4's floor (eval/scifact/runs/2026-10-17-retrieval-bm25.json): nDCG@10 0.6594, recall@200claims 0.9349;
BEIR's BM25 baseline is 0.665. Stages 2 and 3 (verification with a model, belief) are not ported yet.

The data is CC BY-NC 2.0 (SciFact): downloaded into KK_EVAL_CACHE for measurement, never committed.
Results go to kernel/evals/scifact/runs/<date>-retrieval-bm25.json. Uses the PG* environment (a superuser).
"""
from __future__ import annotations

import hashlib
import importlib
import json
import math
import os
import re
import statistics
import sys
import tarfile
import time
import urllib.request
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
KERNEL = HERE.parents[1]
for p in (KERNEL / "src", KERNEL / "providers", KERNEL / "providers" / "validator-shacl",
          KERNEL / "providers" / "recall-bm25"):
    sys.path.insert(0, str(p))

CACHE = Path(os.environ.get("KK_EVAL_CACHE") or Path.home() / ".cache/knowledge-kernel/eval") / "scifact"
FILES = {  # pinned Oct 2026 (rebuild 4)
    "data.tar.gz": ("https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz",
                    "11c621288d41ac144d29b13b0f8503b3820b7d6e8b1f6ff24dff335c196d76be"),
    "beir.zip": ("https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip",
                 "536e14446a0ba56ed1398ab1055f39fe852686ecad24a6306c80c490fa8e0165"),
}
CORPUS, CLAIMS, QRELS = CACHE / "data/corpus.jsonl", CACHE / "data/claims_dev.jsonl", CACHE / "scifact/qrels/test.tsv"
SOURCE = "scifact"
ENCODER = ("t_eval_papers", "urn:kk:agent:encoder-papers", "urn:kk:module:encoder-papers")
READER = "t_eval_reader"
FABIO = "http://purl.org/spar/fabio/"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
TITLE, ABSTRACT = "http://purl.org/dc/terms/title", "http://purl.org/dc/terms/abstract"


def fetch() -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    for name, (url, sha) in FILES.items():
        path = CACHE / name
        if not path.exists():
            urllib.request.urlretrieve(url, path)
        got = hashlib.sha256(path.read_bytes()).hexdigest()
        if got != sha:
            sys.exit(f"{name}: sha256 {got}, expected {sha}")
    with tarfile.open(CACHE / "data.tar.gz") as t:
        t.extractall(CACHE, filter="data")
    zipfile.ZipFile(CACHE / "beir.zip").extractall(CACHE)
    print(json.dumps({"cache": str(CACHE), "papers": sum(1 for _ in open(CORPUS)), "claims": sum(1 for _ in open(CLAIMS))}))


# ---------------------------------------------------------------- the corpus as claims
# As rebuild 4's paper encoder (modules/encoder-papers/paper_encoder/encode.py, parked in rebuild 5):
#   urn:kk:paper:<source>:<id>  a fabio:ResearchPaper ; dcterms:title ; dcterms:abstract
def paper_iri(pid) -> str:
    return f"urn:kk:paper:{SOURCE}:{re.sub(r'[^A-Za-z0-9._-]+', '-', str(pid)).strip('-')}"


def papers(data: bytes) -> list[dict]:
    out = []
    for line in data.decode("utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            abstract = row.get("abstract", "")
            if isinstance(abstract, list):
                abstract = " ".join(s.strip() for s in abstract)
            out.append({"id": str(row["doc_id"]), "title": (row.get("title") or "").strip(), "abstract": abstract.strip()})
    return out


def encode(batch: list[dict], sha: str) -> list[dict]:
    ops = []
    for p in batch:
        s, ref = paper_iri(p["id"]), [{"artifact": sha, "span": {"type": "FragmentSelector", "value": p["id"]}}]

        def claim(pred, obj):
            ops.append({"op": "add_claim", "subject": s, "predicate": pred, "object": obj,
                        "evidence_type": "deterministic", "references": ref})
        claim(RDF_TYPE, {"entity": FABIO + "ResearchPaper"})
        if p["title"]:
            claim(TITLE, {"value": {"@value": p["title"]}})
        if p["abstract"]:
            claim(ABSTRACT, {"value": {"@value": p["abstract"]}})
    return ops


# The terms the dcterms and fabio packs would approve (the pack loader is not ported yet).
TERMS = [("dcterms:title", "owl:DatatypeProperty", "https://www.dublincore.org/specifications/dublin-core/dcmi-terms/"),
         ("dcterms:abstract", "owl:DatatypeProperty", "https://www.dublincore.org/specifications/dublin-core/dcmi-terms/"),
         (FABIO + "ResearchPaper", "owl:Class", "http://purl.org/spar/fabio")]


def setup(db: str) -> None:
    import install
    from kk.lib import connect, run, submit
    from psycopg.types.json import Jsonb
    validator = importlib.import_module("validator.__main__")
    recall_index = importlib.import_module("recall_bm25.__main__")
    t0 = time.time()
    install.install(db, ["validator-shacl", "recall-bm25"])
    url = f"dbname={db}"
    with connect(url=url) as su:
        for role in (ENCODER[0], READER):
            su.execute(f"do $$ begin if not exists (select 1 from pg_roles where rolname = '{role}') then "
                       f"create role {role} nologin; end if; end $$")
            su.execute(f"grant kk_agent to {role}")
        su.execute("set role kk_owner")
        su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, %s, 'software', 'Paper encoder (eval)'),"
                   " ('urn:kk:agent:eval-reader', %s, 'software', 'Eval reader') on conflict do nothing",
                   (ENCODER[1], ENCODER[0], READER))
        su.execute("select kernel.install_ops('eval:scifact-terms', 'urn:kk:scope:vocab', %s)", (Jsonb([
            {"op": "add_claim", "subject": t, "predicate": "rdf:type", "object": {"entity": k},
             "evidence_type": "deterministic", "references": [{"source_uri": src}]} for t, k, src in TERMS]),))
    data = CORPUS.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    store = CACHE / "artifacts"
    store.mkdir(exist_ok=True)
    (store / sha).write_bytes(data)
    rows = papers(data)
    artifact = {"op": "add_artifact", "sha256": sha, "media_type": "application/jsonl", "byte_size": len(data),
                "location": f"file://{store / sha}", "source_uri": "file:corpus.jsonl",
                "retrieved_at": datetime.now(timezone.utc).isoformat()}
    with connect(ENCODER[0], url) as enc, enc.cursor() as cur, run(cur, ENCODER[2], {"papers": len(rows)}) as (run_id, _):
        for i in range(0, len(rows), 500):
            submit(cur, {"idempotency_key": f"papers:{SOURCE}|{sha[:16]}|{i // 500}", "attributed_to": ENCODER[1],
                         "target_scope": "urn:kk:scope:default", "ops": [artifact, *encode(rows[i:i + 500], sha)]}, run_id)
    submitted = time.time() - t0
    with connect("kkm_validator", url) as val:
        validator.drain(val)
    validated = time.time() - t0
    with connect("kkm_recall_index", url) as idx:
        recall_index.Pass()(idx)
    with connect(READER, url) as r:
        n = r.execute("select count(*) from api.claims where subject like 'urn:kk:paper:scifact:%'").fetchone()[0]
    print(json.dumps({"papers": len(rows), "claims": n, "submit_s": round(submitted, 1),
                      "validated_s": round(validated, 1), "indexed_s": round(time.time() - t0, 1)}))


# ---------------------------------------------------------------- stage 1: retrieval
def ndcg10(ranked: list[str], relevant: set[str]) -> float:
    dcg = sum(1 / math.log2(i + 2) for i, d in enumerate(ranked[:10]) if d in relevant)
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(relevant), 10)))
    return dcg / ideal if ideal else 0.0


def retrieval(db: str, limit: int = 200) -> dict:
    from kk import recall
    from kk.lib import connect
    claims = {json.loads(l)["id"]: json.loads(l)["claim"] for l in open(CLAIMS)}
    qrels: dict[str, set[str]] = {}
    for line in open(QRELS).read().splitlines()[1:]:
        q, d, _ = line.split("\t")
        qrels.setdefault(q, set()).add(d)
    prefix = f"urn:kk:paper:{SOURCE}:"
    scores, recalls, ms = [], [], []
    with connect(READER, f"dbname={db}") as conn:
        indexed = recall.indexed(conn)
        for q, rel in sorted(qrels.items(), key=lambda kv: int(kv[0])):
            t0 = time.perf_counter()
            rows = recall.recall(conn, claims[int(q)], limit)
            ms.append((time.perf_counter() - t0) * 1000)
            ranked = list(dict.fromkeys(r["subject"][len(prefix):] for r in rows if r["subject"].startswith(prefix)))
            scores.append(ndcg10(ranked, rel))
            recalls.append(len(rel & set(ranked)) / len(rel))
    ms.sort()
    return {"stage": "retrieval", "queries": len(scores), "ndcg@10": round(statistics.mean(scores), 4),
            f"recall@{limit}claims": round(statistics.mean(recalls), 4),
            "latency_ms": {"p50": round(ms[len(ms) // 2]), "p95": round(ms[int(len(ms) * 0.95)]), "max": round(ms[-1])},
            "baseline": {"bm25_ndcg@10": 0.665, "source": "BEIR (Thakur et al. 2021)",
                         "rebuild4_ndcg@10": 0.6594, "rebuild4_recall@200claims": 0.9349},
            "recall": "api.recall: BM25 over recall-bm25 (k1 1.2, b 0.75)" if indexed else
                      "kk.recall.RANKED (Postgres full-text search, no index)"}


if __name__ == "__main__":
    stage = sys.argv[1] if len(sys.argv) > 1 else ""
    if stage == "fetch":
        fetch()
    elif stage == "setup" and len(sys.argv) == 3:
        setup(sys.argv[2])
    elif stage == "retrieval" and len(sys.argv) == 3:
        result = retrieval(sys.argv[2])
        out = HERE / "runs" / f"{date.today()}-retrieval-bm25.json"
        out.write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))
        floor = result["baseline"]["rebuild4_ndcg@10"]
        sys.exit(0 if result["ndcg@10"] >= floor else f"below rebuild 4's floor {floor}")
    else:
        sys.exit(__doc__)
