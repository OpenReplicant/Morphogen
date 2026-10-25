"""The design agent with a live interviewer (T13, R5-29): Haiku, following morphogen/skills/interview over the kernel
MCP server, records the system a person described in a recorded conversation (morphogen/tests/fixtures/design).

  python3 morphogen/evals/design/run.py setup DB      install Morphogen, record the conversation, make the agent's login
  python3 morphogen/evals/design/run.py claude DB [--model haiku] [--write]
      ask Claude Code headless (claude -p) with only the kernel MCP server, as the agent's own login, then grade
  python3 morphogen/evals/design/run.py reference DB  record the scripted interviewer's claims (notes.yaml), then grade:
      shows the grader passes a correct description (CI's test_design.py runs the same claims end to end)

Graded:
  applied     every change set the agent submitted applied (the validator accepted it)
  quotes      the quote verifier supports every quote the agent's claims carry, against the recorded messages
  no gaps     the agent described the system, and the gap finder lists nothing missing for it
  map         the system the agent described is the expected one (notes.yaml): the same services with the same
              images, connections and settings. Service names are the agent's choice, so services are matched by
              their image
  limit       the entry point's documented limit: bbo:maxValue 0.3 (seconds) on latency-seconds-mean, no other qualifier
  proposable  design-blueprint would propose the file (no open question, no conflict)
Passes when all hold. The validator runs as a service during the agent's session, as in production, so
get_change_set shows each verdict. The agent gets the read tools and start_run, submit_change_set, finish_run, get_change_set;
never review. Uses the PG* environment (a superuser) for setup and grading.
"""
from __future__ import annotations

import argparse
import importlib
import importlib.util
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODULES = ROOT / "morphogen" / "modules"
FIX = ROOT / "morphogen" / "tests" / "fixtures" / "design"
SKILL = ROOT / "morphogen" / "skills" / "interview" / "SKILL.md"
EXPECTED = FIX / "notes.yaml"            # what a correct description holds; never what an agent was given
for p in (ROOT / "kernel" / "src", ROOT / "morphogen" / "src", MODULES, MODULES / "map-gaps", MODULES / "design-blueprint",
          ROOT / "kernel" / "providers" / "validator-shacl", ROOT / "kernel" / "providers" / "verifier-quotes"):
    sys.path.insert(0, str(p))
CACHE = Path(os.environ.get("KK_EVAL_CACHE") or Path.home() / ".cache/knowledge-kernel/eval") / "design"
AGENT = "urn:kk:agent:eval-interviewer"
KKT, BBO = "https://w3id.org/knowledge-kernel/tosca#", "https://www.irit.fr/recherches/MELODI/ontologies/BBO#"
PROP = "http://www.w3.org/ns/sosa/observedProperty"
READ_TOOLS = ["search", "query_claims", "get_entity", "explain", "whoami", "get_change_set"]
WRITE_TOOLS = ["start_run", "submit_change_set", "finish_run"]
NOT_TOOLS = ["review"]


def role(db: str) -> str:
    return f"t_eval_design_{db}"[:63]


def settle(db: str) -> None:
    from kk.lib import connect
    validator = importlib.import_module("validator.__main__")
    with connect("kkm_validator", f"dbname={db}") as val:
        validator.drain(val)


def setup(db: str) -> str:
    import install
    from kk.lib import connect
    from psycopg import sql
    subprocess.run(["dropdb", "--if-exists", "--force", db], check=True)
    subprocess.run(["dropuser", "--if-exists", role(db)], check=True)
    os.environ.setdefault("KK_LOGIN_PASSWORD", secrets.token_hex(16))
    install.install(db, install.modules())
    install.kernel.install(db, ["verifier-quotes"])
    store = CACHE / db / "artifacts"
    shutil.rmtree(CACHE / db, ignore_errors=True)
    store.mkdir(parents=True, mode=0o700)
    out = subprocess.run([sys.executable, "-m", "interview_encoder", "--source", "notes", str(FIX / "notes.jsonl")],
                         cwd=MODULES / "interview-encoder", capture_output=True, text=True,
                         env={**os.environ, "DATABASE_URL": f"dbname={db}", "KK_ARTIFACTS": str(store),
                              "PYTHONPATH": os.pathsep.join([str(MODULES / "interview-encoder"), str(ROOT / "kernel" / "src")])})
    if out.returncode:
        raise SystemExit(f"interview encoder: {out.stderr[-500:]}")
    settle(db)
    pw = secrets.token_urlsafe(24)
    r = sql.Identifier(role(db))
    with connect(url=f"dbname={db}") as su:
        su.execute(sql.SQL("create role {} login").format(r))
        su.execute(sql.SQL("alter role {} password {}").format(r, sql.Literal(pw)))
        su.execute(sql.SQL("grant kk_agent to {}").format(r))
        su.execute(sql.SQL("grant connect on database {} to {}").format(sql.Identifier(db), r))
        su.execute("set role kk_owner")
        su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, %s, 'software', 'Design eval interviewer')"
                   " on conflict do nothing", (AGENT, role(db)))
    f = CACHE / db / "login"
    f.touch(mode=0o600)
    f.write_text(f"dbname={db} user={role(db)} password={pw}\n")
    return f.read_text().strip()


def messages() -> list[dict]:
    rows = [json.loads(x) for x in (FIX / "notes.jsonl").read_text().splitlines() if x.strip()]
    return [{**r, "iri": f"urn:kk:message:notes:notes-intake:{r['id']}"} for r in rows]


def prompt() -> str:
    skill = SKILL.read_text().split("---", 2)[2]
    convo = "\n".join(f"- {m['iri']} ({m['author']}, {'the interviewer' if m.get('kind') == 'agent' else 'the person'}): "
                      f"{m['text']}" for m in messages())
    return f"""You are the interviewer in Morphogen's design agent. Follow this skill:

{skill}

The interview below is over and already recorded by the interview encoder (each message is the IRI shown). Your
task now: record the system the person described, as the skill says, using only the kernel's tools. The system's
name is `notes`. Start one run (start_run, module urn:kk:module:interviewer), then submit one change set per message
of the person's that says something about the system, attributed to your own agent (whoami gives it), with
generated_by your run, each claim quoting that one message; check each with get_change_set and fix what is invalid;
then finish the run. Do not run commands, do not ask questions (the person has left) and do not propose the file.
Reply with one line: the change set ids you submitted.

The conversation:
{convo}
"""


def claude(db: str, model: str) -> str:
    url = (CACHE / db / "login").read_text().strip()
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "KK_DATABASE_URL": url,
           "PYTHONPATH": os.pathsep.join([str(ROOT / "kernel" / "src"), str(ROOT / "kernel" / "providers" / "kernel-mcp")])}
    env.update({k: os.environ[k] for k in ("PGHOST", "PGPORT") if k in os.environ})
    validator = subprocess.Popen([sys.executable, "-m", "validator"], cwd=ROOT / "kernel" / "providers" / "validator-shacl",
                                 env={**os.environ, "DATABASE_URL": f"dbname={db}", "KK_SWEEP_SECONDS": "2",
                                      "PYTHONPATH": str(ROOT / "kernel" / "src")},
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)   # as in production: the agent sees verdicts
    try:
        return _claude(url, env, model)
    finally:
        validator.terminate()
        validator.wait(timeout=30)


def _claude(url: str, env: dict, model: str) -> str:
    config = {"mcpServers": {"kernel": {"command": sys.executable, "args": ["-m", "kernel_mcp"], "env": env}}}
    with tempfile.TemporaryDirectory(prefix="kk-design-") as d:
        f = Path(d) / "mcp.json"
        f.touch(mode=0o600)
        f.write_text(json.dumps(config))
        out = subprocess.run(["claude", "-p", prompt(), "--model", model, "--mcp-config", str(f), "--strict-mcp-config",
                              "--allowedTools", ",".join(f"mcp__kernel__{t}" for t in READ_TOOLS + WRITE_TOOLS),
                              "--disallowedTools", ",".join(f"mcp__kernel__{t}" for t in NOT_TOOLS), "--output-format", "json"],
                             capture_output=True, text=True, timeout=1800, cwd=d,
                             env={k: v for k, v in os.environ.items() if not k.startswith(("PG", "KK_")) and k != "DATABASE_URL"})
    if out.returncode:
        raise SystemExit(f"claude -p failed: {(out.stderr or out.stdout)[-800:]}")
    return json.loads(out.stdout).get("result", "")


def reference(db: str) -> None:
    """Record the scripted interviewer's claims as the eval agent."""
    from kk.lib import connect, run, submit
    spec = importlib.util.spec_from_file_location("test_design", ROOT / "morphogen" / "tests" / "test_design.py")
    t = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t)
    url = (CACHE / db / "login").read_text().strip()
    with connect(url=url) as me, me.cursor() as cur, run(cur, "urn:kk:module:interviewer") as (run_id, _):
        for a in yaml.safe_load((FIX / "notes.yaml").read_text())["answers"]:
            msg = f"urn:kk:message:notes:notes-intake:{a['message']}"
            submit(cur, {"idempotency_key": f"interview:notes|{msg}", "attributed_to": AGENT, "target_scope": "urn:kk:scope:default",
                         "ops": [t.op(row, msg) for row in a["claims"]]}, run_id)


def shape(described: dict) -> dict:
    """A described system with services named by their image: {image: {connects: [images], settings}}."""
    image = {name: d["image"] for name, d in described.items()}
    return {d["image"]: {"connects": sorted(image.get(p) for p in d["connects"]), "command": d["command"],
                         "environment": d["environment"]} for d in described.values()}


def grade(db: str, label: str) -> dict:
    from kk.lib import connect
    from morphogen import blueprint
    from design_blueprint.__main__ import GAPS, OA
    from map_gaps.__main__ import one_pass as find_gaps
    quotes = importlib.import_module("verifier_quotes.__main__")
    settle(db)
    with connect("kkm_verifier_quotes", f"dbname={db}") as v:
        quotes.Pass(CACHE / db / "artifacts", ROOT)(v)
    settle(db)
    with connect("kkm_map_gaps", f"dbname={db}") as conn:
        find_gaps(conn)
    settle(db)
    with connect(url=f"dbname={db}") as su:
        sets = su.execute("select status, count(*) from api.change_sets where attributed_to = %s group by 1", (AGENT,)).fetchall()
        reports = [[k, st, rep] for k, st, rep in su.execute(
            "select idempotency_key, status, validation_report from api.change_sets where attributed_to = %s order by submitted_at",
            (AGENT,)).fetchall()]
        verdicts = dict(su.execute("select coalesce(v.verdict, 'unverified'), count(*) from api.claims c left join api.verifications v "
                                   "on v.claim_id = c.id where c.attributed_to = %s and c.status <> 'deprecated' group by 1",
                                   (AGENT,)).fetchall())
        open_ = [q for _, q in su.execute(GAPS, {"body": OA + "bodyValue", "target": OA + "hasTarget",
                                                 "nodes": "urn:kk:node:notes:%", "system": "urn:kk:system:notes"}).fetchall()]
        cols = ["id", "subject", "predicate", "object_entity", "object_value", "qualifiers"]
        mine = [dict(zip(cols, r)) for r in su.execute(blueprint.MAP + " and attributed_to = %(me)s",
                                                       {**blueprint.params("notes"), "me": AGENT}).fetchall()]
        limits = su.execute("select subject, (object_value->>'@value')::float, qualifiers from api.claims where predicate = %s "
                            "and attributed_to = %s and status <> 'deprecated'", (BBO + "maxValue", AGENT)).fetchall()
    spec = importlib.util.spec_from_file_location("test_design", ROOT / "morphogen" / "tests" / "test_design.py")
    t = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(t)
    script = yaml.safe_load(EXPECTED.read_text())
    want_claims = [{"id": str(i), **o, "object_entity": o["object"].get("entity"), "object_value": o["object"].get("value"),
                    "qualifiers": o.get("qualifiers") or {}}
                   for i, o in enumerate(t.op(row, "x") for a in script["answers"] for row in a["claims"])]
    want = shape(blueprint.described(want_claims, "notes"))
    try:
        got_described = blueprint.described(mine, "notes")
        got, conflict = shape(got_described), None
    except blueprint.Conflict as e:
        got_described, got, conflict = {}, {}, str(e)
    entry = next((n for n, d in got_described.items() if str(d["image"]) == "ghcr.io/example/notes-web:1.4.2" or str(d["image"]).startswith("ghcr.io/example/notes-web:1.4.2@")), None)
    result = {
        "applied": bool(sets) and all(s == "applied" for s, _ in sets),
        "quotes": set(verdicts) == {"supported"},
        "no_gaps": not open_ and bool(mine),
        "map": got == want,
        "limit": any(s == f"urn:kk:node:notes:{entry}" and abs(v - 0.3) < 1e-9 and q == {PROP: "urn:kk:property:latency-seconds-mean"}
                     for s, v, q in limits),
        "proposable": not open_ and conflict is None and bool(got_described),
    }
    result["passed"] = all(result.values())
    detail = {"change_sets": dict(sets), "validation": reports, "verdicts": verdicts, "open_gaps": open_, "described": got_described,
              "expected": want, "conflict": conflict, "limits": [[s, v, q] for s, v, q in limits]}
    for k, v in result.items():
        print(("ok  " if v else "FAIL"), k)
    return {"eval": "design agent (R5-29)", "agent": label, **result, "detail": detail,
            "fixture": "morphogen/tests/fixtures/design/notes.jsonl"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("setup", "reference", "claude"):
        p = sub.add_parser(name)
        p.add_argument("db")
        if name == "claude":
            p.add_argument("--model", default="haiku")
            p.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    if a.cmd == "setup":
        setup(a.db)
        print(f"ready: {a.db}")
        return 0
    if a.cmd == "reference":
        reference(a.db)
        return 0 if grade(a.db, "reference")["passed"] else 1
    reply = claude(a.db, a.model)
    result = grade(a.db, f"claude-code-{a.model}")
    result["reply"] = reply[-2000:]
    if a.write:
        runs = HERE / "runs"
        runs.mkdir(exist_ok=True)
        f = runs / f"{date.today().isoformat()}-{re.sub(r'[^a-z0-9.-]+', '-', result['agent'])}.json"
        f.write_text(json.dumps(result, indent=2, default=str) + "\n")
        print(f"wrote {f.relative_to(ROOT)}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
