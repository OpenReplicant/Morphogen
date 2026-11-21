"""Case custody behind one interface (CLAUDE.md, rail 2: case sets renew).

A store holds named case sets. Each case is {"id", "input", "answer"}. Only the trusted side may hold a
store; the untrusted run gets `inputs()`, which never carries an answer. Four operations:

    cases(name)           the set's cases, with answers (trusted side only)
    claim(name)           count one more verdict against the set; returns the count, this one included
    replace(name, cases)  a fresh set under the same name: new version, count back to 0
    version(name)         the set's current version (changes on every replace)

Two stores ship: `DirStore` (a directory: <root>/<name>/cases.jsonl, served, version) and `GitStore` (a
directory store in a clone of a git repository, each claim or replace a pushed commit, retried on a lost
race). Another store (a database scope the author cannot read, say) only has to provide the same four
operations. Nothing here imports or runs a candidate's code; a generator is the base's own code.
"""

import json
import random
import re
import runpy
import secrets
import shutil
import subprocess
import time
from pathlib import Path

NAME = re.compile(r"[a-z0-9][a-z0-9_.-]{0,63}")


def check_name(name):
    if not isinstance(name, str) or not NAME.fullmatch(name) or ".." in name:
        raise ValueError(f"bad case set name {name!r}")
    return name


def check_cases(cases):
    ids = [c["id"] for c in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate case ids")
    for c in cases:
        if set(c) != {"id", "input", "answer"} or not isinstance(c["id"], str) or not c["id"]:
            raise ValueError(f"a case is {{id, input, answer}} with a string id: {str(c)[:80]}")
    return cases


class DirStore:
    def __init__(self, root):
        self.root = Path(root)

    def _dir(self, name):
        return self.root / check_name(name)

    def cases(self, name):
        rows = [json.loads(line) for line in (self._dir(name) / "cases.jsonl").read_text().splitlines() if line.strip()]
        return check_cases(rows)

    def version(self, name):
        p = self._dir(name) / "version"
        return p.read_text().strip() if p.exists() else ""

    def claim(self, name):
        p = self._dir(name) / "served"
        served = (int(p.read_text().strip() or 0) if p.exists() else 0) + 1
        p.write_text(f"{served}\n")
        return served

    def replace(self, name, cases):
        check_cases(cases)
        d = self._dir(name)
        d.mkdir(parents=True, exist_ok=True)
        (d / "cases.jsonl").write_text("".join(json.dumps(c, sort_keys=True) + "\n" for c in cases))
        (d / "served").write_text("0\n")
        (d / "version").write_text(time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(4) + "\n")


class GitStore:
    """A DirStore in a clone; claim and replace are commits pushed to `branch`, retried on a lost race.
    `auth` is an HTTP Authorization header value, or None (a local path or an ambient credential)."""

    def __init__(self, url, branch="main", workdir="cases", auth=None, attempts=20):
        self.url, self.branch, self.work, self.auth, self.attempts = url, branch, Path(workdir), auth, attempts
        self.dir = DirStore(self.work)

    def _git(self, *args):
        cmd = ["git", "-C", str(self.work), "-c", "user.name=morphogen-judge", "-c", "user.email=judge@invalid"]
        if self.auth:
            cmd += ["-c", f"http.extraHeader=Authorization: {self.auth}"]
        return subprocess.run(cmd + list(args), check=True, capture_output=True, text=True).stdout.strip()

    def _sync(self):
        if not (self.work / ".git").exists():
            self.work.mkdir(parents=True, exist_ok=True)
            self._git("init", "-q", "-b", self.branch)
            self._git("remote", "add", "origin", self.url)
        try:
            self._git("fetch", "-q", "origin", self.branch)
        except subprocess.CalledProcessError:
            return  # an empty repository: nothing to fetch yet
        self._git("reset", "-q", "--hard", "FETCH_HEAD")

    def _commit(self, message, change):
        for _ in range(self.attempts):
            self._sync()
            result = change()
            self._git("add", "-A")
            # A nonce in every commit: two racers making the same change in the same second would
            # otherwise make byte-identical commits, and the loser's push would "succeed" as a no-op.
            self._git("commit", "-qm", f"{message} ({secrets.token_hex(8)})")
            try:
                self._git("push", "-q", "origin", "HEAD:refs/heads/" + self.branch)
                return result
            except subprocess.CalledProcessError:
                time.sleep(random.uniform(0.2, 2))
        raise RuntimeError(f"could not push to the case store after {self.attempts} attempts")

    def cases(self, name):
        self._sync()
        return self.dir.cases(name)

    def version(self, name):
        self._sync()
        return self.dir.version(name)

    def claim(self, name):
        check_name(name)
        return self._commit(f"{name}: served +1", lambda: self.dir.claim(name))

    def replace(self, name, cases):
        check_name(name), check_cases(cases)
        self._commit(f"{name}: renewed", lambda: self.dir.replace(name, cases))


def inputs(store, name):
    """What the untrusted run may see: ids and inputs, in an order that carries nothing."""
    rows = [{"id": c["id"], "input": c["input"]} for c in store.cases(name)]
    secrets.SystemRandom().shuffle(rows)
    return rows


def renew(store, name, generator, n):
    """Replace a set with fresh cases from the base's generator: a file defining generate(rng, n) ->
    [{"id", "input", "answer"}]. The randomness is fresh every time and is never recorded."""
    gen = runpy.run_path(str(generator))["generate"]
    rng = random.Random(secrets.randbits(128))
    cases = gen(rng, n)
    store.replace(name, cases)
    return len(cases)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="python -m judge.store", description="Renew a case set from its generator.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("renew")
    p.add_argument("--dir", required=True, type=Path, help="a directory store (a clone, for a git store)")
    p.add_argument("--set", required=True)
    p.add_argument("--generator", required=True, type=Path)
    p.add_argument("-n", type=int, required=True)
    a = ap.parse_args(argv)
    count = renew(DirStore(a.dir), a.set, a.generator, a.n)
    print(f"{a.set}: {count} fresh cases")


if __name__ == "__main__":
    main()
