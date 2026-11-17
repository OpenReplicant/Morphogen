# End to end on a real forge

A self-hosted Gitea with two Gitea Runners (one per trust level), a toy project with one deciding
KPI and one bound, and an author who opens pull requests from a fork.

Needs Docker. From this directory:

```bash
cp "$(command -v docker)" docker && cp /path/to/cosign-v3.1.4 cosign   # baked into the job image
pip download -d wheels -r judge-requirements.txt --only-binary=:all:
(cd .. && docker build -t morphogen/job:1 -f e2e/job.Dockerfile .)
./up.sh                 # forge, users, runners
python3 probe.py        # what Gitea does with fork pull requests (DECISIONS.md row 8)
python3 toy_setup.py    # toy repo, private case repo, secrets, branch protection
python3 honest.py       # a real fix: signed pass, merge allowed only after it
python3 -m pytest -q redteam.py   # every cheat must be refused
```

The artifact actions are mirrored into the forge's `actions` organisation from github.com and pinned
by commit (DECISIONS.md row 12).
