"""The design agent end to end (T13, R5-29): a person describes a system they want; Morphogen records it, asks
about what it lacks, and writes its compose file once a person approves the text.

  record     the interview encoder records the conversation so far (after the intake filter)
  describe   the interviewer records what each answer says as extracted claims quoting the message
             (tests/fixtures/design: notes.jsonl, and what a correct interviewer records from it, notes.yaml)
  ask        the gap finder lists what the map lacks; each answer closes the gaps it was asked about
  check      the quote verifier supports every quote, against the encoder's record of the message
  propose    design-blueprint refuses while a question is open, then puts the compose file in a review-lane plan
  approve    a person approves it; a description changed after approval is not written
  write      the intent actuator commits the file approved; encoder-compose's map of it is the described map

  PGHOST=... PGUSER=<superuser> python3 morphogen/tests/test_design.py   (needs git and gitleaks)
"""
import importlib
import json
import os
import secrets
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "morphogen" / "modules"
FIX = ROOT / "morphogen" / "tests" / "fixtures" / "design"
sys.path[:0] = [str(ROOT / "kernel" / "src"), str(ROOT / "morphogen" / "src"), str(MODULES),
                 *(str(MODULES / m) for m in ("map-gaps", "design-blueprint", "intent-actuator", "encoder-compose")),
                 str(ROOT / "kernel" / "providers" / "validator-shacl"), str(ROOT / "kernel" / "providers" / "verifier-quotes")]
import install  # noqa: E402  (morphogen/modules/install.py)
from kk.lib import connect, run, submit  # noqa: E402
from morphogen import blueprint  # noqa: E402

from design_blueprint.__main__ import propose  # noqa: E402
from encoder_compose.__main__ import scan  # noqa: E402
from intent_actuator.__main__ import one_pass as actuate  # noqa: E402
from map_gaps.__main__ import one_pass as find_gaps  # noqa: E402

validator = importlib.import_module("validator.__main__")
quotes = importlib.import_module("verifier_quotes.__main__")

DB = "kk_design_test"
INTERVIEWER = "urn:kk:agent:design-test-interviewer"
PERSON = "urn:kk:agent:design-test-person"
KKT, BBO, SOSA = blueprint.KKT, "https://www.irit.fr/recherches/MELODI/ontologies/BBO#", "http://www.w3.org/ns/sosa/"
OA = "http://www.w3.org/ns/oa#"


def check(cond, msg):
    if not cond:
        raise SystemExit(f"CHECK FAILED: {msg}")
    print("ok:", msg, flush=True)


def git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.org", *args],
                          check=True, capture_output=True, text=True).stdout


def op(row: list, message: str) -> dict:
    """One claim of notes.yaml as an add_claim op quoting the message."""
    s, p, o, quote = row
    full = lambda x: {"sys": "urn:kk:system:notes"}.get(x) or (f"urn:kk:node:notes:{x[5:]}" if x.startswith("node:") else  # noqa: E731
                                                              KKT + x[4:] if x.startswith("kkt:") else x)
    pred, quals = {"a": blueprint.RDF_TYPE, "label": "http://www.w3.org/2000/01/rdf-schema#label"}.get(p, full(p)), None
    if p == "image" or p.startswith("setting "):
        pred, quals = KKT + "propertyValue", {KKT + "propertyName": "image" if p == "image" else p.split()[1]}
    elif p.startswith("limit "):
        pred, quals = BBO + "maxValue", {SOSA + "observedProperty": p.split()[1]}
    obj = ({"value": {"@value": o.strip('"')}} if o.startswith('"') else
           {"value": {"@value": float(o)}} if p.startswith("limit ") else {"entity": full(o)})
    c = {"op": "add_claim", "subject": full(s), "predicate": pred, "object": obj, "evidence_type": "extracted",
         "references": [{"source_uri": message, "quote": quote}]}
    if quals:
        c["qualifiers"] = quals
    return c


def main() -> None:
    script = yaml.safe_load((FIX / "notes.yaml").read_text())
    lines = (FIX / "notes.jsonl").read_text().splitlines()
    subprocess.run(["dropdb", "--if-exists", DB], check=True)
    os.environ.setdefault("KK_LOGIN_PASSWORD", secrets.token_hex(16))
    install.install(DB, install.modules())
    install.kernel.install(DB, ["verifier-quotes"])
    url = f"dbname={DB}"
    os.environ["DATABASE_URL"] = url
    with connect(url=url) as su:
        for role, iri, kind, grant in [("t_design_interviewer", INTERVIEWER, "software", "kk_agent"),
                                       ("t_design_person", PERSON, "person", "kk_reviewer")]:
            su.execute(f"do $$ begin if not exists (select 1 from pg_roles where rolname = '{role}') then "
                       f"create role {role} nologin; end if; end $$")
            su.execute(f"grant {grant} to {role}")
            su.execute("set role kk_owner")
            su.execute("insert into kernel.agent(iri, db_role, kind, label) values (%s, %s, %s, %s) on conflict do nothing",
                       (iri, role, kind, role))
            su.execute("reset role")
    tmp = Path(tempfile.mkdtemp())
    intent = tmp / "intent"
    shutil.copytree(ROOT / "morphogen" / "intent", intent)
    git(intent, "init", "-q")
    git(intent, "add", "-A")
    git(intent, "commit", "-qm", "intent")
    store = tmp / "artifacts"
    chat = tmp / "chat" / "notes.jsonl"
    chat.parent.mkdir()
    enc_env = {**os.environ, "KK_ARTIFACTS": str(store),
               "PYTHONPATH": os.pathsep.join([str(MODULES / "interview-encoder"), str(ROOT / "kernel" / "src")])}

    def settle():
        with connect("kkm_validator") as val:
            validator.drain(val)

    def gaps_now() -> list[str]:
        with connect("kkm_map_gaps") as conn:
            find_gaps(conn)
        settle()
        with connect("kkm_map_gaps") as conn:
            rows = conn.execute(
                "select k.object_entity, t.object_entity from api.claims t join api.claims k on k.subject = t.subject "
                "and k.predicate = 'http://purl.org/dc/terms/type' and k.status <> 'deprecated' "
                "where t.predicate = %s and t.attributed_to = 'urn:kk:agent:map-gaps' and t.status <> 'deprecated'",
                (OA + "hasTarget",)).fetchall()
        return sorted(f"{k.rsplit(':', 1)[-1]} {t.rsplit(':', 1)[-1]}" for k, t in rows)

    try:
        with connect("kkm_design_blueprint") as conn:
            refused = propose(conn, "notes", intent)
        check("refused" in refused, f"nothing is proposed for a system nobody has described ({refused['refused']})")
        for n, answer in enumerate(script["answers"]):
            upto = next(i for i, x in enumerate(lines) if json.loads(x)["id"] == answer["message"])
            chat.write_text("\n".join(lines[:upto + 1]) + "\n")
            out = subprocess.run([sys.executable, "-m", "interview_encoder", "--source", "notes", str(chat)],
                                 cwd=MODULES / "interview-encoder", env=enc_env, capture_output=True, text=True)
            check(out.returncode == 0 and not json.loads(out.stdout)["skipped"],
                  f"record: the conversation up to message {answer['message']} ({out.stderr.strip()[-200:]})")
            settle()
            message = f"urn:kk:message:notes:notes-intake:{answer['message']}"
            with connect("t_design_interviewer") as me, me.cursor() as cur, run(cur, "urn:kk:module:design-test") as (run_id, _):
                res = submit(cur, {"idempotency_key": f"interview:notes|{message}", "attributed_to": INTERVIEWER,
                                   "target_scope": "urn:kk:scope:default",
                                   "ops": [op(row, message) for row in answer["claims"]]}, run_id)
            settle()
            with connect("t_design_interviewer") as me:
                status = me.execute("select status from api.change_sets where id = %s", (res["id"],)).fetchone()[0]
            check(status == "applied", f"describe: what answer {n + 1} says is recorded, quoting message {answer['message']}")
            got = gaps_now()
            check(got == sorted(answer["open"]), f"ask: after answer {n + 1} the map lacks {got or 'nothing'}")
            if n == 0:
                with connect("kkm_design_blueprint") as conn:
                    refused = propose(conn, "notes", intent)
                check(refused.get("refused") == "questions not answered yet" and len(refused["gaps"]) == 4,
                      "propose: refused while the person's answers are still owed (the open questions are named)")

        with connect("kkm_verifier_quotes") as v:
            quotes.Pass(store, ROOT)(v)
        settle()
        with connect("t_design_interviewer") as me:
            verdicts = me.execute("select v.verdict, count(*) from api.claims c left join api.verifications v on v.claim_id = c.id "
                                  "where c.attributed_to = %s group by 1", (INTERVIEWER,)).fetchall()
        total = sum(len(a["claims"]) for a in script["answers"])
        check(verdicts == [("supported", total)],
              f"check: the quote verifier finds every quote in the person's recorded message ({verdicts})")

        with connect("kkm_design_blueprint") as conn:
            first = propose(conn, "notes", intent)
        settle()
        with connect("t_design_person") as person:
            queued = person.execute("select 1 from api.review_queue where id = %s", (first["change_set"],)).fetchall()
        check(queued, "propose: the plan waits for a person in the review queue")
        check("plan" in first and "ghcr.io/example/notes-api:1.4.2" in first["text"] and "LOG_LEVEL: info" in first["text"],
              "propose: with no question open, the compose file goes to review as a plan carrying its text")
        with connect("t_design_person") as person:
            person.execute("select api.review(%s, true, 'as described')", (first["change_set"],))
        # The interviewer changes a setting after the person approved: what is written must be what was approved.
        with connect("t_design_interviewer") as me, me.cursor() as cur, run(cur, "urn:kk:module:design-test") as (run_id, _):
            old = me.execute("select id, subject, predicate, qualifiers, valid_from, status from api.claims where attributed_to = %s "
                             "and qualifiers->>%s = 'LOG_LEVEL'", (INTERVIEWER, KKT + "propertyName")).fetchall()
            change = {"idempotency_key": "interview:notes|late-change", "attributed_to": INTERVIEWER,
                      "target_scope": "urn:kk:scope:default",
                      "ops": [op(["node:api", "setting LOG_LEVEL", '"debug"', "LOG_LEVEL"], "urn:kk:message:notes:notes-intake:6")]}
            from kk.changes import supersede
            supersede(change, [dict(zip(("id", "subject", "predicate", "qualifiers", "valid_from", "status"), r)) for r in old])
            submit(cur, change, run_id)
        settle()
        with connect("kkm_intent_actuator") as conn:
            report = actuate(conn, intent, "sandbox")
        check([r["status"] for r in report.values()] == ["failed"] and "is not the file" in next(iter(report.values()))["error"]
              and not (intent / "systems" / "notes").exists(),
              "approve: a description changed after approval is not written (the approved text is bound by its sha256)")

        with connect("kkm_design_blueprint") as conn:
            second = propose(conn, "notes", intent)
        settle()
        with connect("t_design_person") as person:
            queued = person.execute("select 1 from api.review_queue where id = %s", (second["change_set"],)).fetchall()
        check(queued, "propose: the plan waits for a person in the review queue")
        with connect("t_design_person") as person:
            person.execute("select api.review(%s, true, 'with debug logging')", (second["change_set"],))
        with connect("kkm_intent_actuator") as conn:
            report = actuate(conn, intent, "sandbox")
        f = intent / "systems" / "notes" / "compose.yaml"
        done = [r for r in report.values() if r["status"] == "succeeded"]
        check(len(done) == 1 and f.read_text() == second["text"] and blueprint.sha(f.read_text()) == second["sha256"],
              "write: the actuator writes the approved file")
        log = git(intent, "log", "-1", "--format=%s")
        check(log.startswith(f"change-set:{second['change_set']}") and not git(intent, "status", "--porcelain"),
              "write: one commit naming the change set that recorded the plan")

        scan("notes", f, intent)
        settle()
        with connect("kkm_encoder_compose") as conn:
            rows = conn.execute(blueprint.MAP + " and attributed_to = 'urn:kk:agent:encoder-compose'", blueprint.params("notes")).fetchall()
            mine = conn.execute(blueprint.MAP + " and attributed_to = %(me)s", {**blueprint.params("notes"), "me": INTERVIEWER}).fetchall()
        cols = ["id", "subject", "predicate", "object_entity", "object_value", "qualifiers"]
        encoded = blueprint.described([dict(zip(cols, r)) for r in rows], "notes")
        said = blueprint.described([dict(zip(cols, r)) for r in mine], "notes")
        check(encoded == said, "write: encoder-compose's map of the file is the system as the person described it")
        check(gaps_now() == [], "the system has no open question once its file is mapped")
        with connect("kkm_design_blueprint") as conn:
            again = propose(conn, "notes", intent)
        check("compose file already" in again.get("refused", ""), "propose: a system with a compose file is not created again")

        # Another agent's plan: its label shows a harmless file, its step names what the record renders.
        def describe(system, rows, key):
            with connect("t_design_interviewer") as me, me.cursor() as cur, run(cur, "urn:kk:module:design-test") as (run_id, _):
                ops = [op(r, "urn:kk:message:notes:notes-intake:6") for r in rows]
                for o in ops:
                    o["subject"] = o["subject"].replace(":notes:", f":{system}:").replace("system:notes", f"system:{system}")
                    if "entity" in o["object"]:
                        o["object"]["entity"] = o["object"]["entity"].replace(":notes:", f":{system}:").replace("system:notes", f"system:{system}")
                submit(cur, {"idempotency_key": key, "attributed_to": INTERVIEWER, "target_scope": "urn:kk:scope:default", "ops": ops}, run_id)
            settle()
        base = [["node:app", "a", "kkt:NodeTemplate", "run the API"], ["node:app", "kkt:memberOf", "sys", "run the API"],
                ["node:app", "image", '"ghcr.io/example/notes-api:1.4.2@sha256:7b2e047b2e047b2e047b2e047b2e047b2e047b2e047b2e047b2e047b2e047b2e"', "run the API"],
                ["node:app", "limit urn:kk:property:latency-seconds-mean", "0.3", "run the API"]]
        describe("forge", base + [["node:app", "setting MODE", '"evil"', "run the API"]], "interview:forge")
        rendered = blueprint.render(blueprint.described(
            [dict(zip(["id", "subject", "predicate", "object_entity", "object_value", "qualifiers"], r)) for r in
             connect(url=url).execute(blueprint.MAP, blueprint.params("forge")).fetchall()], "forge"), "forge")
        from design_blueprint.__main__ import plan as make_plan
        forged = make_plan("forge", rendered, [])
        forged["attributed_to"], forged["idempotency_key"] = INTERVIEWER, "forged"
        for o in forged["ops"]:
            o.pop("derived_from")
            o.update(evidence_type="extracted", references=[{"source_uri": "urn:kk:message:notes:notes-intake:6", "quote": "run the API"}])
            if o["predicate"].endswith("#label"):
                o["object"] = {"value": {"@value": blueprint.label("forge", "services:\n  app:\n    image: harmless:1\n")}}
        with connect("t_design_interviewer") as me, me.cursor() as cur, run(cur, "urn:kk:module:design-test") as (run_id, _):
            fid = str(submit(cur, forged, run_id)["id"])
        settle()
        with connect("t_design_person") as person:
            person.execute("select api.review(%s, true, 'looks harmless')", (fid,))
        with connect("kkm_intent_actuator") as conn:
            report = actuate(conn, intent, "sandbox")
        check(not (intent / "systems" / "forge").exists() and any("design-blueprint proposed" in r.get("error", "") for r in report.values()),
              "write: a plan another agent made, with a label that is not the file, is not carried out though a person approved it")

        describe("vault", base + [["node:app", "setting AWS_ACCESS_KEY_ID", '"AKIA' + 'Q3EGRTZ7OVMW2KX5"', "run the API"]], "interview:vault")
        gaps_now()
        with connect("kkm_design_blueprint") as conn:
            secret = propose(conn, "vault", intent)
        check("intake filter found a secret" in secret.get("refused", ""),
              f"propose: a secret in a setting is not put in a plan or a file ({secret.get('refused')})")

        # An image named by tag only: the gap finder asks for its digest, and nothing is proposed until it is pinned
        # (the compose runner runs only pinned images, so what runs is what a person approved).
        tagged = [r if r[1] != "image" else ["node:app", "image", '"ghcr.io/example/notes-api:1.4.2"', "run the API"] for r in base]
        before = gaps_now()
        describe("tagged", tagged, "interview:tagged")
        asked = [g for g in gaps_now() if g not in before or before.remove(g)]
        with connect("kkm_design_blueprint") as conn:
            held = propose(conn, "tagged", intent)
        check(asked == ["unpinned-image app"] and held.get("refused") == "questions not answered yet"
              and any("sha256" in q for q in held["gaps"]),
              f"ask: an image named by tag only is asked to be pinned by digest before anything is proposed ({asked}, {held})")

        # The person gives the digest: the interviewer records the pinned image and supersedes the tag claim by it,
        # in one change set, as the interview skill says. The question closes and the file can be proposed.
        pinned_image = "ghcr.io/example/notes-api:1.4.2@sha256:" + "7b2e04" * 10 + "7b2e"
        with connect("t_design_interviewer") as me:
            tag_claim = str(me.execute("select id from api.claims where subject = 'urn:kk:node:tagged:app' and predicate = %s "
                                       "and status <> 'deprecated' and object_value->>'@value' = 'ghcr.io/example/notes-api:1.4.2'",
                                       (KKT + "propertyValue",)).fetchone()[0])
            with me.cursor() as cur, run(cur, "urn:kk:module:design-test") as (run_id, _):
                new = op(["node:app", "image", f'"{pinned_image}"', "run the API"], "urn:kk:message:notes:notes-intake:6")
                new["subject"] = "urn:kk:node:tagged:app"
                submit(cur, {"idempotency_key": "interview:tagged|2", "attributed_to": INTERVIEWER, "target_scope": "urn:kk:scope:default",
                             "ops": [{**new, "ref": "img"},
                                     {"op": "set_status", "claim": tag_claim, "status": "deprecated", "reason": "superseded",
                                      "replaced_by": "img", "expect_status": "normal"}]}, run_id)
        settle()
        with connect("t_design_interviewer") as me:
            by = me.execute("select s.status, s.reason, c.object_value->>'@value' from kernel.claim_status s join api.claims c "
                            "on c.id = s.replaced_by where s.claim_id = %s", (tag_claim,)).fetchall()
        check(by == [("deprecated", "superseded", pinned_image)],
              f"pin: the tag claim is superseded by the pinned image, which the record names as its replacement ({by})")
        gaps_now()                                        # the gap finder runs again: the question is answered
        with connect("kkm_design_blueprint") as conn:
            pinned = propose(conn, "tagged", intent)      # refused while any question on the system is open
        check("plan" in pinned and pinned_image in pinned["text"],
              f"pin: the question closes and the pinned file goes to review ({pinned.get('refused')}, {pinned.get('gaps')})")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        subprocess.run(["dropdb", "--force", DB], check=True)
    print("design agent test passed")


if __name__ == "__main__":
    main()
