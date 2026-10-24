"""Self-model questions (rebuild 4 eval/self-model, T16 gate G7): questions about the system's own structure,
answered from its self-model by an agent over the kernel MCP server, citing claim ids and showing belief.

  python kernel/evals/self-model/run.py setup DB [--distribution FILE ...] [--providers DIR ...]
      install the record, validator, belief model and self-encoder into DB; scan the blueprint, the provider
      manifests (and each --providers directory) and each distribution; validate; score belief; make the
      agent's own login (KK_EVAL_CACHE/self-model/<DB>.login, root's alone)
  python kernel/evals/self-model/run.py reference DB [--questions FILE]
      the reference agent: each question answered with query_claims from its `evidence` pattern, then graded.
      Deterministic: shows the self-model holds every answer, citable (CI runs it)
  python kernel/evals/self-model/run.py grade DB --answers FILE [--questions FILE] [--label NAME]
      grade a live agent's answers (JSON [{id, answer}]) and write runs/<date>-<label>.json
  python kernel/evals/self-model/run.py claude DB [--model haiku] [--questions FILE] [--write]
      ask Claude Code headless (claude -p) with only the kernel MCP server, as the agent's own login, then
      grade (rebuild 4's --claude; the gate runs use Haiku)
  python kernel/evals/self-model/run.py tool DB NAME [JSON]
      call one MCP tool as the agent and print its result: how a sub-agent without MCP of its own asks
  python kernel/evals/self-model/run.py prompt [--questions FILE]
      the prompt a live agent gets (the questions, never their evidence)

Graded as rebuild 4 graded it (scripts/eval_self.py):
  correct   every `expect` term (or the value `expect_from` reads, file:key) appears in the answer and is the
            subject or object of a claim the answer cites (grounded); no `exclude` term is both named and
            backed by a cited claim of the question's predicate
  cited     the answer cites at least one claim id, and every cited id resolves with `explain`
  belief    the answer shows belief (the word and a number)
Passes (G7) at >= 90% correct, with every correct answer cited and showing belief. Rebuild 4's floor: 12/12
with Claude Code (eval/self-model/runs/2026-10-16-claude-code.json). Answers are read and explained over
MCP stdio as the agent's own login, which can read but not switch roles. Uses the PG* environment (a
superuser) for setup and to locate the database.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import re
import secrets
import subprocess
import sys
from datetime import date
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
KERNEL = HERE.parents[1]
ROOT = KERNEL.parent
for p in (KERNEL / "src", KERNEL / "providers", KERNEL / "providers" / "validator-shacl",
          KERNEL / "providers" / "belief-corroboration", KERNEL / "providers" / "self-encoder"):
    sys.path.insert(0, str(p))

QUESTIONS = HERE / "questions.yaml"
CACHE = Path(os.environ.get("KK_EVAL_CACHE") or Path.home() / ".cache/knowledge-kernel/eval") / "self-model"
AGENT = "urn:kk:agent:eval-self"
PROVIDERS = ["pack-loader", "validator-shacl", "belief-corroboration", "self-encoder"]
UUID = re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b")
BELIEF = re.compile(r"belief[^0-9]{0,20}(0(\.\d+)?|1(\.0+)?)\b", re.I)


# ------------------------------------------------------------------ setup

def settle(db: str) -> None:
    """Validate what was submitted, score belief, validate the belief claims."""
    from kk.lib import connect, follow
    validator = importlib.import_module("validator.__main__")
    belief = importlib.import_module("belief_corroboration.__main__")
    with connect("kkm_validator", f"dbname={db}") as val:
        validator.drain(val)
        with connect("kkm_belief", f"dbname={db}") as bel:
            follow(bel, belief.Pass(), once=True)
        validator.drain(val)


def agent_login(db: str) -> str:
    """The agent's own login (made once per database): reads under kk_agent, switches to no other role."""
    from kk.lib import connect
    from psycopg import sql
    ROLE = f"t_eval_self_{db}"[:63]                     # roles are the cluster's: one per database
    CACHE.mkdir(parents=True, exist_ok=True, mode=0o700)
    pw = secrets.token_urlsafe(24)
    with connect(url=f"dbname={db}") as su:
        su.execute(f"do $$ begin if not exists (select 1 from pg_roles where rolname = '{ROLE}') then "
                   f"create role {ROLE} login; end if; end $$")
        su.execute(sql.SQL("alter role {} password {}").format(sql.Identifier(ROLE), sql.Literal(pw)))
        su.execute(f"grant kk_agent to {ROLE}")
        su.execute(f'grant connect on database "{db}" to {ROLE}')
        su.execute("set role kk_owner")
        su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, %s, 'software', 'Self-model eval agent')"
                   " on conflict do nothing", (AGENT, ROLE))
    f = CACHE / f"{db}.login"
    f.touch(mode=0o600)
    f.chmod(0o600)
    f.write_text(f"dbname={db} user={ROLE} password={pw}\n")
    return f.read_text().strip()


def setup(db: str, distributions: list[str] = (), providers: list[str] = (), install=None) -> str:
    """Install, scan, settle; returns the agent's login. `install(db)` replaces the kernel's install (a
    distribution installs its own modules as well)."""
    import install as kernel_install
    encoder = importlib.import_module("self_encoder.__main__")
    subprocess.run(["dropdb", "--if-exists", "--force", db], check=True)
    (install or (lambda d: kernel_install.install(d, PROVIDERS)))(db)
    os.environ["DATABASE_URL"] = f"dbname={db}"
    for r in encoder.scan(ROOT, list(distributions), [], list(providers)):
        if r.get("status") not in ("submitted", "applied", "unchanged"):
            raise SystemExit(f"self-encoder: {r}")
    settle(db)
    return agent_login(db)


def login(db: str) -> str:
    f = CACHE / f"{db}.login"
    if not f.exists():
        raise SystemExit(f"no agent login for {db}: run setup first")
    return f.read_text().strip()


# ------------------------------------------------------------------ MCP

def session(url: str):
    from mcp import StdioServerParameters
    from mcp.client.stdio import stdio_client
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "HOME", "PGHOST", "PGPORT")}
    env.update(PYTHONPATH=os.pathsep.join([str(KERNEL / "src"), str(KERNEL / "providers" / "kernel-mcp")]),
               KK_DATABASE_URL=url)
    return stdio_client(StdioServerParameters(command=sys.executable, args=["-m", "kernel_mcp"], env=env))


async def tool(s, name: str, args: dict):
    res = await s.call_tool(name, args)
    text = res.content[0].text if res.content else ""
    if res.is_error:
        raise RuntimeError(text)
    sc = res.structured_content
    return sc.get("result", sc) if sc else json.loads(text)


async def call_one(url: str, name: str, args: dict):
    from mcp import ClientSession
    async with session(url) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        return await tool(s, name, args)


# ------------------------------------------------------------------ answering and grading

def local(iri: str) -> str:
    return re.split(r"[#/:]", str(iri).rstrip("/#"))[-1]


def obj(c: dict) -> str:
    return local(c["object_entity"]) if c.get("object_entity") else str((c.get("object_value") or {}).get("@value"))


def expected(q: dict) -> list[str]:
    if "expect_from" in q:
        path, key = q["expect_from"].rsplit(":", 1)
        return [str(yaml.safe_load((ROOT / path).read_text())[key])]
    return [str(e) for e in q["expect"]]


def matches(c: dict, ev: dict) -> bool:
    """The parts of an evidence pattern query_claims does not filter on: a value and qualifiers."""
    if "value" in ev and str((c.get("object_value") or {}).get("@value")) != str(ev["value"]):
        return False
    quals = c.get("qualifiers") or {}
    return all(any(k.endswith(name.split(":")[-1]) and str(v) == str(want) for k, v in quals.items())
               for name, want in (ev.get("qualifiers") or {}).items())


async def reference(url: str, questions: list[dict]) -> list[dict]:
    from mcp import ClientSession
    answers = []
    async with session(url) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        for q in questions:
            ev = q["evidence"]
            found = await tool(s, "query_claims", {k: ev[k] for k in ("subject", "predicate", "object_entity") if k in ev})
            found = [c for c in found if matches(c, ev)]
            side = (lambda c: local(c["subject"])) if q["answer"] == "subject" else obj
            parts = [f"{side(c)} (claim {c['id']}, belief {c['belief'] if c['belief'] is not None else 'none'})"
                     for c in found]
            answers.append({"id": q["id"], "answer": "; ".join(parts) or "not found"})
    return answers


async def grade(url: str, questions: list[dict], answers: list[dict]) -> list[dict]:
    from mcp import ClientSession
    by_id = {a["id"]: str(a.get("answer", "")) for a in answers}
    results = []
    async with session(url) as (r, w), ClientSession(r, w) as s:
        await s.initialize()
        for q in questions:
            text = by_id.get(q["id"], "")
            words = {w.strip(".,;:()[]\"'").lower() for w in re.split(r"[\s/#]+", text)} | \
                    {local(w).strip(".,;:()[]\"'").lower() for w in re.split(r"\s+", text) if ":" in w}
            cited = sorted(set(UUID.findall(text)))
            explained = []
            for cid in cited:
                try:
                    explained.append((await tool(s, "explain", {"claim_id": cid}))["claim"])
                except (RuntimeError, KeyError, TypeError):
                    explained.append(None)
            resolved = bool(cited) and all(explained)
            grounded = set().union(*({local(c["subject"]).lower(), obj(c).lower()} for c in explained if c))
            pred = q["evidence"]["predicate"].split(":")[-1]
            asserted = {(local(c["subject"]) if q["answer"] == "subject" else obj(c)).lower()
                        for c in explained if c and re.split(r"[#/]", c["predicate"])[-1] == pred}
            correct = all(e.lower() in words and e.lower() in grounded for e in expected(q)) and \
                not any(x.lower() in asserted and x.lower() in words for x in q.get("exclude", []))
            belief = bool(BELIEF.search(text))
            results.append({"id": q["id"], "correct": correct, "cited": len(cited), "resolved": resolved,
                            "belief": belief, "answer": text})
            print(("ok  " if correct and resolved and belief else "FAIL"), q["id"], q["question"],
                  f"[correct={correct} cited={len(cited)} resolved={resolved} belief={belief}]",
                  text[:160].replace("\n", " "), flush=True)
    return results


def score(questions: list[dict], results: list[dict], label: str, qfile: Path) -> dict:
    n = len(questions)
    correct = sum(r["correct"] for r in results)
    cited = all(r["resolved"] for r in results if r["correct"])
    belief = all(r["belief"] for r in results if r["correct"])
    passed = n > 0 and correct / n >= 0.9 and cited and belief
    print(f"G7 self-questions {'passed' if passed else 'FAILED'} ({label}): {correct}/{n} correct "
          f"({correct / max(n, 1):.0%}), citations resolve: {cited}, belief shown: {belief}")
    return {"set": str(qfile.relative_to(ROOT)), "agent": label, "questions": n, "correct": correct,
            "accuracy": round(correct / max(n, 1), 4), "citations_resolve": cited, "belief_shown": belief,
            "passed": passed, "floor": {"rebuild4": "12/12 (eval/self-model/runs/2026-10-16-claude-code.json)",
                                        "gate": ">= 90% correct, cited, belief shown"},
            "results": results}


PROMPT = """You answer questions about a software system's own structure from its knowledge kernel, a record of
claims. Use only the kernel's tools (search, query_claims, get_entity, explain, list_slots); CURIEs such as
kk:fills, rdfs:label, owl:versionInfo, dcterms:hasPart, kkt:connectsTo work as predicates. Slots are
urn:kk:slot:<id>, providers urn:kk:provider:<name>, distributions urn:kk:distribution:<id>, managed systems
urn:kk:system:<name> with services urn:kk:node:<system>:<service>. For every answer cite the claim ids you
relied on and show each claim's belief, e.g. "validator-shacl (claim <uuid>, belief 0.50)". Name only what
the claims support. Reply with only a JSON array: [{"id": "<question id>", "answer": "<answer with
citations and beliefs>"}].

Questions:
"""


def prompt(questions: list[dict]) -> str:
    return PROMPT + "\n".join(f"- {q['id']}: {q['question']}" for q in questions)


def claude(url: str, questions: list[dict], model: str) -> list[dict]:
    import tempfile
    env = {"PATH": os.environ.get("PATH", ""), "HOME": os.environ.get("HOME", ""), "KK_DATABASE_URL": url,
           "PYTHONPATH": os.pathsep.join([str(KERNEL / "src"), str(KERNEL / "providers" / "kernel-mcp")])}
    env.update({k: os.environ[k] for k in ("PGHOST", "PGPORT") if k in os.environ})
    config = {"mcpServers": {"kernel": {"command": sys.executable, "args": ["-m", "kernel_mcp"], "env": env}}}
    with tempfile.TemporaryDirectory(prefix="kk-self-") as d:
        f = Path(d) / "mcp.json"
        f.touch(mode=0o600)
        f.write_text(json.dumps(config))
        out = subprocess.run(["claude", "-p", prompt(questions), "--model", model, "--mcp-config", str(f),
                              "--strict-mcp-config", "--allowedTools", "mcp__kernel", "--output-format", "json"],
                             capture_output=True, text=True, timeout=1800, cwd=d)
    if out.returncode:
        raise SystemExit(f"claude -p failed: {(out.stderr or out.stdout)[-800:]}")
    result = json.loads(out.stdout)["result"]
    return json.loads(result[result.index("["):result.rindex("]") + 1])


def write_run(result: dict, label: str, qfile: Path) -> Path:
    runs = qfile.parent / "runs"
    runs.mkdir(exist_ok=True)
    out = runs / f"{date.today().isoformat()}-{re.sub(r'[^a-z0-9.-]+', '-', label.lower())}.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("setup")
    s.add_argument("db")
    s.add_argument("--distribution", action="append", default=[])
    s.add_argument("--providers", action="append", default=[])
    for name in ("reference", "grade", "claude"):
        g = sub.add_parser(name)
        g.add_argument("db")
        g.add_argument("--questions", type=Path, default=QUESTIONS)
        g.add_argument("--label", default=name)
        g.add_argument("--write", action="store_true", help="write runs/<date>-<label>.json next to the questions")
        if name == "grade":
            g.add_argument("--answers", type=Path, required=True)
        if name == "claude":
            g.add_argument("--model", default="haiku")
    t = sub.add_parser("tool")
    t.add_argument("db")
    t.add_argument("name")
    t.add_argument("args", nargs="?", default="{}")
    pr = sub.add_parser("prompt")
    pr.add_argument("--questions", type=Path, default=QUESTIONS)
    a = ap.parse_args(argv)
    if a.cmd == "setup":
        setup(a.db, a.distribution, a.providers)
        print(f"ready: {a.db}; the agent's login is in {CACHE / (a.db + '.login')}")
        return 0
    if a.cmd == "tool":
        print(json.dumps(asyncio.run(call_one(login(a.db), a.name, json.loads(a.args))), indent=1, default=str))
        return 0
    qfile = (a.questions if a.questions.is_absolute() else Path.cwd() / a.questions).resolve()
    questions = yaml.safe_load(qfile.read_text())["questions"]
    if a.cmd == "prompt":
        print(prompt(questions))
        return 0
    url = login(a.db)
    if a.cmd == "claude":
        answers = claude(url, questions, a.model)
        a.label = a.label if a.label != "claude" else f"claude-code-{a.model}"
    else:
        answers = asyncio.run(reference(url, questions)) if a.cmd == "reference" else json.loads(a.answers.read_text())
    result = score(questions, asyncio.run(grade(url, questions, answers)), a.label, qfile)
    if a.write:
        print(f"wrote {write_run(result, a.label, qfile).relative_to(ROOT)}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
