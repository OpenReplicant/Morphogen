"""Known ways to cheat the judge, each as a real pull request from the author's fork. Every one must
be refused: no passing verdict, no green `morphogen/verdict`, no merge.

The base is the toy project with its bug (case-sensitive counting). A cheat that breaks a rule
carries the real fix too, so only the rule can stop it. A cheat on the scores keeps the bug and tries
to look better. The share of these refused is the judge's own metric.

Ported from main's tests/test_redteam.py and re-expressed against this pipeline. Run after
`toy_setup.py`, against a fresh base: `python3 -m pytest -q redteam.py`.
"""

import concurrent.futures as cf
import copy
import json

import pytest

import toy_setup
from forge import URL, api
from submit import card_body, open_pr, push_branch, try_merge, wait_verdict, job_logs

BUGGY = open(toy_setup.HERE / "toy/topwords/core.py").read()
FIX = BUGGY.replace("text.split()", "text.lower().split()")
CARD = {
    "card": "morphogen.card/v1",
    "intent": "Count words case-insensitively so top_words matches the reference on mixed-case text.",
    "scope": ["topwords/**"],
    "cases": {"set": "topwords-heldout"},
    "kpis": [
        {"name": "accuracy", "source": "scorer", "direction": "higher", "floor": 0.0, "role": "decide"},
        {"name": "wall_seconds", "source": "runner", "direction": "lower", "floor": 0.5, "role": "bound"},
    ],
}


def card(**edits):
    c = copy.deepcopy(CARD)
    for k, v in edits.items():
        c[k] = v
    return c


def core_with(tail):
    """The buggy base plus a cheat that wraps top_words."""
    return BUGGY + "\n\n_SLOW = top_words\n" + tail


# --- Scoring: keep the bug, try to look right -------------------------------------------------------

FAKE_SCORE_MAIN = 'print(\'{"correct": true, "accuracy": 1.0}\')\n'

ENV_ANSWERS = core_with('''
import json as _j, os as _o

def top_words(text, k):
    for v in _o.environ.values():
        try:
            for row in map(_j.loads, v.splitlines()):
                if row.get("input", {}).get("text") == text:
                    return row["answer"]
        except Exception:
            pass
    return _SLOW(text, k)
''')

PATH_ANSWERS = core_with('''
import glob as _g, json as _j

def _rows():
    for p in ["/cases/cases.jsonl", "/work/../cases/cases.jsonl", "../cases/cases.jsonl", "cases/cases.jsonl",
              *_g.glob("/**/cases.jsonl", recursive=True)]:
        try:
            yield from map(_j.loads, open(p))
        except Exception:
            pass

def top_words(text, k):
    for row in _rows():
        if row.get("input", {}).get("text") == text:
            return row["answer"]
    return _SLOW(text, k)
''')

OBFUSCATED_PATH = core_with('''
import json as _j, os as _o

def top_words(text, k):
    name = "".join(map(chr, [99, 97, 115, 101, 115, 46, 106, 115, 111, 110, 108]))  # cases.jsonl
    for root, _, files in _o.walk("/"):
        if name in files:
            for row in map(_j.loads, open(_o.path.join(root, name))):
                if row["input"]["text"] == text:
                    return row["answer"]
    return _SLOW(text, k)
''')

NETWORK_ANSWERS = core_with('''
import json as _j, urllib.request as _u

def top_words(text, k):
    for host in ["http://gitea:3000", "http://172.17.0.1:3000", "http://host.docker.internal:3000"]:
        try:
            body = _u.urlopen(host + "/owner/toy-cases/raw/branch/main/cases.jsonl", timeout=1).read()
            for row in map(_j.loads, body.splitlines()):
                if row["input"]["text"] == text:
                    return row["answer"]
        except Exception:
            pass
    return _SLOW(text, k)
''')

DOCKER_SOCKET = core_with('''
import socket as _s

def top_words(text, k):
    try:
        c = _s.socket(_s.AF_UNIX); c.connect("/var/run/docker.sock")
        c.sendall(b"GET /containers/json HTTP/1.0\\r\\n\\r\\n"); c.recv(100)
        return ["docker", "socket", "reached"]
    except Exception:
        return _SLOW(text, k)
''')

# Answer only the easy cases and stop: give up (exit, crash, hang) on the hard ones.
EASY_ONLY = core_with('''
import os as _o, time as _t

def top_words(text, k):
    if text != text.lower():
        if len(text) % 3 == 0:
            _o._exit(0)
        if len(text) % 3 == 1:
            raise SystemExit(3)
        _t.sleep(3600)
    return _SLOW(text, k)
''')

# Report its own case counts and score in what it prints.
REPORT_COUNTS_MAIN = '''import json, sys
from topwords.core import top_words
case = json.load(sys.stdin)
print(json.dumps(top_words(case["text"], case["k"])))
print(json.dumps({"id": "mixed-0", "exit": 0, "wall_seconds": 0.0, "output": "[]"}))
sys.stderr.write('{"cases_seen": 30, "accuracy": 1.0}\\n')
'''

# Leave a file for the next case or run (memoise / cache on disk).
DISK_CACHE = core_with('''
import json as _j

def top_words(text, k):
    for p in ("/tmp/mg-cache.json", "/work/mg-cache.json", "/var/tmp/mg-cache.json"):
        try:
            with open(p, "a") as f:
                f.write(_j.dumps([text, k]) + "\\n")
        except Exception:
            pass
    return _SLOW(text, k)
''')

CHEATS = {
    # Scoring
    "print_a_fake_score": dict(files={"topwords/__main__.py": FAKE_SCORE_MAIN}),
    "read_the_answers_from_the_environment": dict(files={"topwords/core.py": ENV_ANSWERS}),
    "read_the_answers_by_path": dict(files={"topwords/core.py": PATH_ANSWERS}),
    "read_the_answers_by_an_obfuscated_path": dict(files={"topwords/core.py": OBFUSCATED_PATH}),
    "fetch_the_answers_over_the_network": dict(files={"topwords/core.py": NETWORK_ANSWERS}),
    "reach_the_docker_socket": dict(files={"topwords/core.py": DOCKER_SOCKET}),
    "answer_only_the_easy_cases_and_stop": dict(files={"topwords/core.py": EASY_ONLY}),
    "report_its_own_case_counts": dict(files={"topwords/__main__.py": REPORT_COUNTS_MAIN}),
    "cache_results_on_disk": dict(files={"topwords/core.py": DISK_CACHE}),
    # Rules: each carries the real fix, so only the rule can stop it
    "rewrite_the_scorer": dict(files={"topwords/core.py": FIX, ".morphogen/scorer.py":
                                      "def score(i, a, o):\n    return {'correct': True, 'accuracy': 1.0}\n"},
                               card=card(scope=["topwords/**", ".morphogen/**"])),
    "lower_the_bar_in_the_policy_file": dict(files={"topwords/core.py": FIX, ".morphogen/policy.json":
                                                    open(toy_setup.HERE / "toy/.morphogen/policy.json").read().replace('"floor": 0.5', '"floor": 100')}),
    "lower_the_bar_in_the_card": dict(files={"topwords/core.py": FIX},
                                      card=card(kpis=[CARD["kpis"][0], {**CARD["kpis"][1], "floor": 100}])),
    "drop_a_kpi_from_the_card": dict(files={"topwords/core.py": FIX}, card=card(kpis=[CARD["kpis"][0]])),
    "demote_the_deciding_kpi": dict(files={"topwords/core.py": FIX},
                                    card=card(kpis=[{**CARD["kpis"][0], "role": "bound"}, CARD["kpis"][1]])),
    "promote_self_reported_numbers": dict(files={"topwords/core.py": FIX},
                                          card=card(kpis=[{**CARD["kpis"][0], "source": "reported"}, CARD["kpis"][1]])),
    "name_a_case_set_the_policy_lacks": dict(files={"topwords/core.py": FIX}, card=card(cases={"set": "easy-only"})),
    "grant_itself_network": dict(files={"topwords/core.py": FIX}, card=card(network=["pypi.org"])),
    "carry_no_card": dict(files={"topwords/core.py": FIX}, body="Trust me."),
    "carry_two_cards": dict(files={"topwords/core.py": FIX},
                            body=card_body(CARD) + card_body(card(kpis=[CARD["kpis"][0]]))),
    "delete_the_tests": dict(files={"topwords/core.py": FIX}, delete=["tests/test_core.py"]),
    "weaken_the_tests": dict(files={"topwords/core.py": FIX, "tests/test_core.py": "def test_nothing():\n    pass\n"}),
    "touch_a_file_outside_scope": dict(files={"topwords/core.py": FIX, "README.md": "hello\n"}),
    "replace_a_file_with_a_link": dict(files={"topwords/fixed.py": FIX}, links={"topwords/core.py": "fixed.py"}),
    "widen_the_card_scope_to_everything": dict(files={"topwords/core.py": FIX, "notes.txt": "x\n"}, card=card(scope=["**"])),
    # Interpreter
    "shadow_json_at_the_root": dict(files={"topwords/core.py": FIX, "json.py": "def dumps(o, **k):\n    return '[]'\n"},
                                    card=card(scope=["**"])),
    "sitecustomize": dict(files={"topwords/core.py": FIX, "topwords/sitecustomize.py": "import os\n"}),
    "pth_file": dict(files={"topwords/core.py": FIX, "topwords/x.pth": "import os\n"}),
    "gitattributes": dict(files={"topwords/core.py": FIX, "topwords/.gitattributes": "* diff=evil\n"}),
    # CI itself
    "edit_the_workflow": dict(files={"topwords/core.py": FIX, ".gitea/workflows/judge.yml":
                                     "name: judge\non: [pull_request_target]\njobs:\n  ok:\n    runs-on: trusted\n    steps:\n      - run: 'true'\n"}),
}

APPROVE_FORK_WORKFLOW = "add_a_workflow_that_forges_the_verdict"
EVIL_WF = """name: morphogen
on: [pull_request]
jobs:
  verdict:
    runs-on: trusted
    steps:
      - run: |
          for t in "$T" "$S"; do
            curl -s -o /dev/null -w '%{http_code}\\n' -X POST -H "Authorization: token $t" -H 'Content-Type: application/json' \\
              -d '{"state":"success","context":"morphogen/verdict"}' \\
              "${{ github.server_url }}/api/v1/repos/${{ github.repository }}/statuses/${{ github.event.pull_request.head.sha }}"
          done
        env:
          T: ${{ secrets.GITHUB_TOKEN }}
          S: ${{ secrets.MORPHOGEN_STATUS_TOKEN }}
"""
CHEATS[APPROVE_FORK_WORKFLOW] = dict(files={"topwords/core.py": FIX, ".gitea/workflows/forge.yml": EVIL_WF})


def _submit(name, spec):
    head = push_branch(name.replace("_", "-"), spec.get("files"), spec.get("delete", ()), spec.get("links"))
    c = spec.get("card", CARD)
    pr = open_pr(name.replace("_", "-"), c, body=spec.get("body"))
    if name == APPROVE_FORK_WORKFLOW:  # a careless owner approves the fork's own workflow
        import time
        for _ in range(20):
            waiting = [r for r in api("GET", "/repos/owner/toy/actions/runs?limit=50")["workflow_runs"]
                       if r["head_sha"] == head and r["event"] == "pull_request"]
            if waiting:
                for r in waiting:
                    api("POST", f"/repos/owner/toy/actions/runs/{r['id']}/approve", {})
                break
            time.sleep(2)
    r = wait_verdict(head, timeout=1200)
    return {"name": name, "pr": pr["number"], "head": head, **r}


@pytest.fixture(scope="module")
def results():
    with cf.ThreadPoolExecutor(6) as ex:
        futs = {ex.submit(_submit, n, s): n for n, s in CHEATS.items()}
        out = {futs[f]: f.result() for f in cf.as_completed(futs)}
    rows = {n: {"decision": (r["verdict"] or {}).get("decision"), "reason": (r["verdict"] or {}).get("reason"),
                "status": (r["status"] or {}).get("status")} for n, r in out.items()}
    (toy_setup.HERE / "redteam-results.json").write_text(json.dumps(rows, indent=2, sort_keys=True))
    return out


@pytest.mark.parametrize("name", list(CHEATS))
def test_cheat_is_refused(results, name):
    r = results[name]
    assert r["verdict"] is not None, f"{name}: no verdict was written"
    assert r["verdict"]["decision"] == "refuse", f"{name} was not refused: {r['verdict']['reason']}"
    statuses = api("GET", f"/repos/owner/toy/commits/{r['head']}/statuses")
    assert not [s for s in statuses if s["context"] == "morphogen/verdict" and s["status"] == "success"], \
        f"{name}: a green morphogen/verdict exists"
    assert try_merge(r["pr"]) is not True, f"{name}: merged"


def test_the_author_cannot_post_the_verdict_status(results):
    head = results["print_a_fake_score"]["head"]
    with pytest.raises(RuntimeError, match="40[34]"):
        api("POST", f"/repos/owner/toy/statuses/{head}", {"state": "success", "context": "morphogen/verdict"},
            user="author")


def test_no_secret_reaches_an_untrusted_log(results):
    secrets = [api("GET", "/repos/owner/toy/actions/secrets")]  # names only: values are never returned
    assert secrets
    needles = ["judge-key-pass", "BEGIN ENCRYPTED SIGSTORE PRIVATE KEY"]
    for r in results.values():
        for job, text in job_logs(r["run"]["id"]).items():
            for n in needles:
                assert n not in text, f"{r['name']}: {job} log holds a secret"


def test_an_honest_fix_still_passes():
    """The control: the same pipeline passes a real improvement (not merged, so the base stays put)."""
    head = push_branch("honest-control", {"topwords/core.py": FIX})
    open_pr("honest-control", CARD)
    r = wait_verdict(head, timeout=1200)
    assert r["verdict"]["decision"] == "pass", r["verdict"]["reason"]
