"""The slot harness (kernel/contract/slots/harness.py) refuses to run a provider's service as a role with more rights
than an agent has, and drops every role it made. Uses the PG* environment, like psql; run as a superuser.

  python3 kernel/providers/tests/test_harness.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "contract" / "slots"))
from harness import Record  # noqa: E402

PROVIDER = ROOT / "providers" / "truth-maintenance"


def check(cond, msg):
    if not cond:
        sys.exit(f"FAIL: {msg}")
    print("ok:", msg)


def refused(rec: Record, role: str) -> str:
    try:
        rec.service_once(PROVIDER, role=role)
    except SystemExit as e:
        return str(e)
    return ""


rec = Record("kkc_harness", [PROVIDER])
try:
    rec.agent("kkc_harness_plain", "urn:kk:agent:contract-plain")
    rec.agent("kkc_harness_val", "urn:kk:agent:contract-val", grants=("kk_validator",))
    rec.agent("kkc_harness_steward", "urn:kk:agent:contract-steward2", kind="person", grants=("kk_steward",))
    for role in ("kkc_harness_val", "kkc_harness_steward", "kk_owner", rec.su.info.user, "kkc_harness_nobody"):
        check("refused" in refused(rec, role), f"service_once refuses role {role}")
    with rec.su.cursor() as cur:
        cur.execute("create role kkc_harness_bare nologin")
    rec.made.append("kkc_harness_bare")
    check("refused" in refused(rec, "kkc_harness_bare"), "service_once refuses a role that is not an agent")
    check(not refused(rec, "kkm_truth_maintenance"), "service_once runs the provider's own role")
    made = list(rec.made)
finally:
    rec.drop()
left = Record("kkc_harness_after", [], packs=False)
try:
    rows = left.rows("select rolname from pg_roles where rolname = any(%s)", (made,))
finally:
    left.drop()
check(made and not rows, f"drop() removes every role the record made ({len(made)})")
