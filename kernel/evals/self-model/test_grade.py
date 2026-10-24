"""The grader fails what it should: on a database `run.py setup` made, the reference answers pass, and each
broken answer fails the way it is broken (a green eval counts only after it has failed with the logic broken).

  PGHOST=... PGUSER=<superuser> python3 kernel/evals/self-model/test_grade.py DB   (after run.py setup DB)
"""
import asyncio
import importlib.util
import re
import sys
from pathlib import Path

import yaml

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("self_model", HERE / "run.py")
ev = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ev)


def check(cond: bool, msg: str) -> None:
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print(f"ok: {msg}", flush=True)


def main(db: str) -> None:
    url = ev.login(db)
    questions = yaml.safe_load(ev.QUESTIONS.read_text())["questions"]
    q = {x["id"]: x for x in questions}
    ref = {a["id"]: a["answer"] for a in asyncio.run(ev.reference(url, questions))}
    first = lambda qid: re.search(ev.UUID, ref[qid]).group(0)   # noqa: E731
    everything = asyncio.run(ev.call_one(url, "query_claims", {"predicate": "kk:fills"}))
    lic = asyncio.run(ev.call_one(url, "query_claims", {"subject": "urn:kk:provider:record-postgres",
                                                        "predicate": "dcterms:license"}))[0]["id"]
    slot_claim = asyncio.run(ev.call_one(url, "query_claims", {"subject": "urn:kk:slot:evaluator"}))[0]["id"]
    self_fills = next(c["id"] for c in everything if c["subject"].endswith(":self-encoder"))
    cases = [
        ("q01", "validator-shacl, belief 0.5", "an answer that cites no claim"),
        ("q03", "kernel-mcp (claim 00000000-0000-4000-8000-000000000000, belief 0.5)", "a cited id that does not resolve"),
        ("q08", "; ".join(f"{ev.local(c['subject'])} (claim {c['id']}, belief 0.5)" for c in everything),
         "citing every provider, the excluded ones too"),
        ("q12", f"verifier-quotes (claim {first('q08')}, belief 0.5)", "another provider, with its own claim cited"),
        ("q07", f"vocabulary-pack (claim {first('q07')})", "a right answer that does not show belief"),
        ("q06", f"one (claim {first('q11')}, belief 0.5)", "the right word, grounded in a claim about another slot"),
        ("q05", f"Apache-2.0 (claim {lic}, belief 0.5)", "the right licence, cited from another provider's claim"),
        ("q12", f"The evaluator slot is filled by self-encoder (claim {self_fills}, claim {slot_claim}, belief 0.5)",
         "the question's own word, cited from claims that do not answer it"),
    ]
    for k, answer, what in cases:
        r = asyncio.run(ev.grade(url, [q[k]], [{"id": k, "answer": answer}]))[0]
        check(not (r["correct"] and r["resolved"] and r["belief"]), f"{k} fails: {what}")
    good = asyncio.run(ev.grade(url, questions, [{"id": k, "answer": v} for k, v in ref.items()]))
    check(ev.score(questions, good, "reference", ev.QUESTIONS)["passed"], "the reference answers pass")
    wrong = {"q01": cases[0][1], "q12": cases[3][1]}
    two_wrong = [{"id": k, "answer": wrong.get(k, v)} for k, v in ref.items()]
    result = ev.score(questions, asyncio.run(ev.grade(url, questions, two_wrong)), "two wrong", ev.QUESTIONS)
    check(not result["passed"] and result["correct"] == 10, "two wrong answers of twelve fail the gate (under 90%)")
    print("self-model grader tests passed")


if __name__ == "__main__":
    main(sys.argv[1])
