"""Rail 2: cases sit behind a store interface (fetch, claim, replace), and sets renew from a generator."""

import json
import subprocess
import threading
from pathlib import Path

import pytest

from judge import store

CASES = [{"id": f"c{i}", "input": {"n": i}, "answer": i * 2} for i in range(5)]


def git(*a, cwd=None):
    return subprocess.run(["git", *a], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(params=["dir", "git"])
def st(request, tmp_path):
    if request.param == "dir":
        s = store.DirStore(tmp_path / "cases")
    else:
        bare = tmp_path / "cases.git"
        git("init", "-q", "--bare", "-b", "main", str(bare))
        s = store.GitStore(str(bare), branch="main", workdir=tmp_path / "clone")
    s.replace("toy", CASES)
    return s


def test_cases_round_trip_and_inputs_never_carry_answers(st):
    assert st.cases("toy") == CASES
    ins = store.inputs(st, "toy")
    assert sorted(r["id"] for r in ins) == [c["id"] for c in CASES]
    assert all(set(r) == {"id", "input"} for r in ins)
    assert "answer" not in json.dumps(ins)


def test_claim_counts_and_replace_renews(st):
    assert [st.claim("toy") for _ in range(3)] == [1, 2, 3]
    v1 = st.version("toy")
    st.replace("toy", CASES[:2])
    assert st.cases("toy") == CASES[:2] and st.claim("toy") == 1 and st.version("toy") != v1


@pytest.mark.parametrize("bad", ["../x", "a/b", "", ".hidden", "A" * 80])
def test_set_names_cannot_escape_the_store(st, bad):
    with pytest.raises(ValueError):
        st.cases(bad)


def test_duplicate_ids_are_refused(st):
    with pytest.raises(ValueError):
        st.replace("toy", CASES + CASES[:1])


def test_concurrent_git_claims_all_count(tmp_path):
    bare = tmp_path / "cases.git"
    git("init", "-q", "--bare", "-b", "main", str(bare))
    store.GitStore(str(bare), branch="main", workdir=tmp_path / "seed").replace("toy", CASES)
    got = []
    def one(i):
        got.append(store.GitStore(str(bare), branch="main", workdir=tmp_path / f"w{i}").claim("toy"))
    ts = [threading.Thread(target=one, args=(i,)) for i in range(6)]
    [t.start() for t in ts]; [t.join() for t in ts]
    assert sorted(got) == [1, 2, 3, 4, 5, 6]


def test_renew_from_a_generator(tmp_path):
    gen = tmp_path / "gen.py"
    gen.write_text("def generate(rng, n):\n"
                   "    return [{'id': f'g{i}', 'input': rng.randrange(1000), 'answer': None} for i in range(n)]\n")
    s = store.DirStore(tmp_path / "cases")
    store.renew(s, "toy", gen, 7)
    first = s.cases("toy")
    store.renew(s, "toy", gen, 7)
    assert len(first) == 7 and s.cases("toy") != first   # fresh randomness each time
