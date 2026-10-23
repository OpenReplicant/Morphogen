"""The split rule: kernel/ never depends on morphogen/.

kernel/ must be extractable into its own repository with `git filter-repo --path kernel/`.
Fails if any file under kernel/ imports or references the distribution.
"""
import pathlib
import re
import sys

root = pathlib.Path(__file__).resolve().parents[1]
bad = []
pattern = re.compile(r"(^|\W)(import\s+morphogen|from\s+morphogen|\.\./morphogen|morphogen/)")
for p in (root / "kernel").rglob("*"):
    if p.is_file() and p.suffix in {".py", ".sql", ".sh", ".yaml", ".yml", ".json", ".toml"}:
        for n, line in enumerate(p.read_text(errors="ignore").splitlines(), 1):
            if pattern.search(line) and "distributions (morphogen/distribution.yaml)" not in line:
                bad.append(f"{p.relative_to(root)}:{n}: {line.strip()}")
for b in bad:
    print("kernel depends on morphogen:", b)
print("boundary ok" if not bad else f"{len(bad)} boundary violation(s)")
sys.exit(1 if bad else 0)
