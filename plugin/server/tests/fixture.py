"""A throwaway git project with the slow-script sample committed on main."""

import shutil
import subprocess
import tempfile
from pathlib import Path

from morphogen import judge as judge_mod
from morphogen import project
from morphogen.config import load_config

TARGET = "targets/slow-script"


def git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


class SampleProject:
    def __init__(self, trials_per_day: int = 0):
        self.tmp = Path(tempfile.mkdtemp())
        self.repo = self.tmp / "proj"
        self.repo.mkdir()
        git(self.repo, "init", "-q", "-b", "main")
        git(self.repo, "config", "user.email", "t@example.com")
        git(self.repo, "config", "user.name", "test")
        project.init_project(self.repo)
        project.install_sample(self.repo, "slow-script", None)
        cfg_file = self.repo / "morphogen.yaml"
        cfg_file.write_text(cfg_file.read_text().replace("sandbox: auto", "sandbox: none")
                            .replace("trials_per_day: 20", f"trials_per_day: {trials_per_day}"))
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        self.cfg = load_config(self.repo)
        _, self.evidence = project.stores(self.repo, self.cfg)

    def path(self, rel):
        return self.repo / TARGET / rel

    def branch(self, name, files=None, delete=()):
        """Commit a candidate on `name`: files maps target-relative paths to new text."""
        git(self.repo, "checkout", "-q", "-B", name, "main")
        for rel, text in (files or {}).items():
            p = self.path(rel)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text)
        for rel in delete:
            self.path(rel).unlink()
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", name)
        git(self.repo, "checkout", "-q", "main")
        return name

    def judge(self, candidate):
        return judge_mod.judge(self.repo, self.cfg, TARGET, "main", candidate, self.evidence)

    def original(self, rel):
        return self.path(rel).read_text()

    def close(self):
        shutil.rmtree(self.tmp)


FAST = '''"""Most frequent words in a text."""
from collections import Counter


def normalise(text):
    words = [w.strip(".,;:!?\\"'()[]").lower() for w in text.split()]
    return [w for w in words if w]


def top_words(text, k):
    counts = Counter(normalise(text))
    return sorted(counts.items(), key=lambda p: (-p[1], p[0]))[:k]
'''
