# Set up on Gitea (self-hosted)

The judge runs on Gitea Actions with two Gitea Runners, one per trust level. Tested on Gitea 28.3.0
and Gitea Runner 5.3.0 (`e2e/`). The workflow is [`e2e/toy/.gitea/workflows/judge.yml`](../e2e/toy/.gitea/workflows/judge.yml).

```bash
cd e2e && ./up.sh            # forge, an owner and an author, two runners
python3 toy_setup.py         # toy repository, private cases, secrets, branch protection
python3 honest.py            # a real fix: signed pass, merge allowed only after it
python3 -m pytest -q redteam.py
```

What Gitea does differently, measured (`e2e/probe.py`):

- `pull_request_target` runs the **base's** workflow, with secrets, even when a fork edits it.
- A fork's own `pull_request` workflow waits for approval; once approved it gets no secrets and its
  token cannot post a status, but it **can choose any runner by label**. So a label is not a security
  boundary: the held-out answers must never sit on a runner's disk. They come from a secret.
- Gitea has commit statuses, not check runs, and no merge queue: require the `morphogen/verdict` status
  and "block merge if the pull request is outdated".
- Verdicts are signed with a cosign key pair held as a secret (`--signing-config` with no transparency
  log); publish `judge.pub`.

A self-hosted runner must never run a public repository's pull requests: use GitHub-hosted runners
for public projects.
