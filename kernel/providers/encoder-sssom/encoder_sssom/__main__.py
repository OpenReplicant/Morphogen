"""SSSOM encoder: mapping sets into the record as proposed mappings (R5-51, the mapping-set slot). A plain command.

  python -m encoder_sssom import [--artifacts DIR] FILE ...
      each SSSOM/TSV file (encode.py) into one change set in the vocabulary scope, keyed by the set's
      mapping_set_id and the file's sha256, the file itself kept as an artifact (copied to DIR under its sha256)
      that every claim references. Every claim is a skos:*Match, so the change set waits for a person (the lane
      policy's review predicates); nothing it proposes is followed by a reader before then. The same file again
      submits nothing. A new version of a set (same mapping_set_id, other content) proposes only the mappings not
      already current and retracts the current ones it no longer has, in the same change set, which a person
      approves whole (retracting a mapping is reviewed too, R5-51). A file the spec says to reject records nothing.

Prints one JSON line per file: the change set and its status, how many mappings it proposes and retracts, and
the rows skipped with why (a predicate that is not a SKOS mapping property, a negated mapping).
Env: DATABASE_URL (the provider's own login, or one that may SET ROLE to KK_ROLE), KK_ROLE (default kkm_encoder_sssom),
KK_ARTIFACTS (default ~/.local/share/knowledge-kernel/artifacts).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from kk.lib import connect, run, submit

from . import encode

MODULE = "urn:kk:module:encoder-sssom"
AGENT = "urn:kk:agent:encoder-sssom"
SCOPE = "urn:kk:scope:vocab"
KEY = "sssom:"

# This agent's current claims from earlier versions of a set: change sets keyed `sssom:<mapping_set_id>|<sha256>`, the set
# id compared whole (an id may itself contain '|').
CURRENT = """select c.id::text, c.subject, c.predicate, c.object_entity, c.qualifiers, c.status
             from api.claims c join api.change_sets s on s.id = c.change_set
             where c.attributed_to = %s and c.status <> 'deprecated'
               and left(s.idempotency_key, -64) = %s and right(s.idempotency_key, 64) ~ '^[0-9a-f]{64}$'"""


def same(subject: str, predicate: str, obj: str, qualifiers: dict | None) -> str:
    return json.dumps([subject, predicate, obj, qualifiers or {}], sort_keys=True)


def record(cur, rel: str, data: bytes, store: Path) -> dict:
    text = data.decode("utf-8")
    sha = hashlib.sha256(data).hexdigest()
    meta, _ = encode.read(text)
    ops, skipped = encode.encode(rel, sha, text)
    prefix = f"{KEY}{meta['mapping_set_id']}|"
    cur.execute(CURRENT, (AGENT, prefix))
    current = {same(s, p, o, q): (i, st) for i, s, p, o, q, st in cur.fetchall()}
    new = [op for op in ops if same(op["subject"], op["predicate"], op["object"]["entity"], op.get("qualifiers")) not in current]
    keep = {same(op["subject"], op["predicate"], op["object"]["entity"], op.get("qualifiers")) for op in ops}
    gone = [{"op": "set_status", "claim": i, "status": "deprecated", "expect_status": st, "reason": "retracted"}
            for k, (i, st) in sorted(current.items()) if k not in keep]
    out = {"file": rel, "mapping_set_id": meta["mapping_set_id"], "sha256": sha, "proposed": len(new),
           "retracted": len(gone), "skipped": skipped}
    if not new and not gone:
        return {**out, "status": "unchanged"}
    if not (store / sha).exists():
        store.mkdir(parents=True, exist_ok=True)
        (store / f"{sha}.part").write_bytes(data)
        (store / f"{sha}.part").rename(store / sha)
    artifact = {"op": "add_artifact", "sha256": sha, "media_type": "text/tab-separated-values", "byte_size": len(data),
                "location": f"file://{store / sha}", "source_uri": f"file:{rel}",
                "retrieved_at": datetime.now(timezone.utc).isoformat()}
    cs = {"idempotency_key": f"{prefix}{sha}", "attributed_to": AGENT, "target_scope": SCOPE,
          "ops": [artifact] + new + gone}
    with run(cur, MODULE, {"file": rel, "sha256": sha, "mapping_set_id": meta["mapping_set_id"]}) as (run_id, outputs):
        res = submit(cur, cs, run_id)
        outputs.update(proposed=len(new), retracted=len(gone), skipped=len(skipped))
    return {**out, "change_set": str(res["id"]), "status": res["status"]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="encoder_sssom")
    sub = ap.add_subparsers(dest="cmd", required=True)
    imp = sub.add_parser("import")
    imp.add_argument("--artifacts", default=os.environ.get("KK_ARTIFACTS")
                     or str(Path.home() / ".local/share/knowledge-kernel/artifacts"))
    imp.add_argument("files", nargs="+")
    a = ap.parse_args(argv)
    failed = 0
    with connect(os.environ.get("KK_ROLE", "kkm_encoder_sssom")) as conn:
        for f in a.files:
            try:
                with conn.transaction(), conn.cursor() as cur:
                    print(json.dumps(record(cur, Path(f).name, Path(f).read_bytes(), Path(a.artifacts))), flush=True)
            except encode.SSSOMError as e:
                print(json.dumps({"file": f, "status": "refused", "why": str(e)}), flush=True)
                failed = 1
    return failed


if __name__ == "__main__":
    sys.exit(main())
