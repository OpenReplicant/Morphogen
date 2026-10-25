"""The evaluator slot's own runner (set.yaml `runner:`): runs one provider's command on run files as its own role and
reads what it recorded. Prints "ok: <case id>" per passing case. Never imports the provider.

  python3 runner.py <provider directory>
"""
import hashlib
import json
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from harness import Record, check  # noqa: E402

C = "urn:kk:contract:evaluator/"
DQV = "http://www.w3.org/ns/dqv#"
SUBJECT = "http://purl.org/dc/terms/subject"
RUN = "urn:kk:eval:contract-suite:run-1"
PROVIDER = "urn:kk:provider:some-candidate"


def main(provider: Path) -> int:
    rec = Record("kkc_evaluator", [provider])
    try:
        me = rec.agent_of(provider)
        d = Path(tempfile.mkdtemp(prefix="kkc-evaluator-"))
        store = d / "artifacts"
        f = d / "run-1.json"
        first = {"provider": PROVIDER, "dataset": "dev", "models": {"m": 3},
                 "accuracy": 0.75, "recall": {"at5": 0.9, "at10": 1}, "per_case": [1, 0, 1], "complete": True}
        f.write_text(json.dumps(first))

        def evaluate():
            since = rec.now()
            rec.service_once(provider, args=("--suite", "contract-suite", "--artifacts", str(store), str(f)))
            return since

        def measurements(current=True):
            return {(c["qualifiers"].get(DQV + "isMeasurementOf"), c["qualifiers"].get(DQV + "computedOn")):
                    (Decimal(str(c["object_value"]["@value"])), c) for c in rec.rows(
                        "select c.*, (select status from kernel.claim_status s where s.claim_id = c.id order by recorded_at desc limit 1) st "
                        "from api.claims c where subject = %s and predicate = %s" + (" and status <> 'deprecated'" if current else ""),
                        (RUN, DQV + "value"))}
        evaluate()
        got = measurements()
        want = {("urn:kk:metric:contract-suite:accuracy", "urn:kk:dataset:contract-suite:dev"): Decimal("0.75"),
                ("urn:kk:metric:contract-suite:recall.at5", "urn:kk:dataset:contract-suite:dev"): Decimal("0.9"),
                ("urn:kk:metric:contract-suite:recall.at10", "urn:kk:dataset:contract-suite:dev"): Decimal("1")}
        ok = True
        ok &= check({k: v for k, (v, _) in got.items()} == want, C + "one-per-number", str({k: v for k, (v, _) in got.items()}))
        sha = hashlib.sha256(f.read_bytes()).hexdigest()
        refs = {str(c["id"]): rec.rows("select artifact, source_uri from kernel.claim_reference where claim_id = %s", (c["id"],))
                for _, c in got.values()}
        stored = store / sha
        ok &= check(got and all(c["evidence_type"] == "observed" for _, c in got.values())
                    and all(any(r["artifact"] == sha for r in rs) for rs in refs.values())
                    and stored.is_file() and hashlib.sha256(stored.read_bytes()).hexdigest() == sha,
                    C + "observed-and-referenced", str(refs))
        named = rec.rows("select object_entity from api.claims where subject = %s and predicate = %s and status <> 'deprecated'",
                         (RUN, SUBJECT))
        ok &= check([r["object_entity"] for r in named] == [PROVIDER], C + "names-provider", str(named))
        sets = rec.rows("select cs.attributed_to, r.agent, r.module from kernel.change_set cs join kernel.run r on r.id = cs.generated_by "
                        "where cs.id in (select change_set from kernel.claim where subject = %s)", (RUN,))
        ok &= check(sets and all(s["attributed_to"] == me and s["agent"] == me for s in sets), C + "attributed", str(sets))

        since = evaluate()
        again = rec.rows("select id from kernel.change_set where attributed_to = %s and submitted_at > %s::timestamptz", (me, since))
        ok &= check(not again and measurements().keys() == got.keys(), C + "same-file", f"{len(again)} new change sets")

        f.write_text(json.dumps({**first, "accuracy": 0.8}))
        evaluate()
        now = measurements()
        old = {str(c["id"]) for _, c in got.values()}
        ok &= check({k: v for k, (v, _) in now.items()} == {**want, ("urn:kk:metric:contract-suite:accuracy", "urn:kk:dataset:contract-suite:dev"): Decimal("0.8")}
                    and not old & {str(c["id"]) for _, c in now.values()}
                    and all(r["status"] == "deprecated" for r in rec.rows("select status from api.claims where id = any(%s::uuid[])", (sorted(old),))),
                    C + "changed-file", str({k: v for k, (v, _) in now.items()}))
        return 0 if ok else 1
    finally:
        rec.drop()


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]).resolve()))
