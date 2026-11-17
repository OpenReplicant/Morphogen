# Judging pull requests on GitHub

The judge runs as the reusable workflow `.github/workflows/judge.yml` in this repository, called from
a ten-line `pull_request_target` workflow in your repository (`morphogen.yml` here). Because the
trigger is `pull_request_target`, GitHub always uses the definition on your default branch, so a pull
request cannot change what judges it.

## Set up (once, by the repository owner)

1. **Policy and scorer on the default branch.** `.morphogen/policy.json` (schema: `schemas/policy.v1.json`)
   and `.morphogen/scorer.py` (`score(input, answer, output) -> {"correct": bool, <kpi>: number}`).
2. **A private repository of held-out cases**, one directory per case set: `<set>/cases.jsonl`
   (`{"id", "input", "answer"}` per line). The judge keeps the count of verdicts served in `<set>/served`.
3. **An environment named `morphogen-judge`** (Settings → Environments), with deployment branches
   limited to your default branch, holding:
   - `MORPHOGEN_CASES_TOKEN`: a fine-grained token with *Contents: read and write* on the case repository only.
   - `MORPHOGEN_COSIGN_KEY` and `MORPHOGEN_COSIGN_PASSWORD`: from `cosign generate-key-pair` (not needed
     with `signing: keyless`). Publish `cosign.pub` so anyone can check a verdict.

   Only the `admit` and `score` jobs name this environment; the job that runs the candidate cannot read it.
4. **Copy `morphogen.yml`** to `.github/workflows/`, replacing `JUDGE_SHA` (both places, the same commit),
   `OWNER/CASES` and `your_module`.
5. **A ruleset on the default branch** (Settings → Rules): require the status check `morphogen/verdict`,
   with its source set to *GitHub Actions*, and require branches to be up to date before merging.
6. **Fork pull requests from outside collaborators.** Anyone with write access can post statuses, so the
   people whose changes are judged must not have write access.

## Check a verdict

Download the `verdict` artifact from the run, then:

```bash
cosign verify-blob --key cosign.pub --bundle verdict.sigstore.json --insecure-ignore-tlog=true verdict.json
```

With `signing: keyless`, verify the workflow identity instead:

```bash
cosign verify-blob --bundle verdict.sigstore.json verdict.json \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github.com/OpenReplicant/Morphogen/\.github/workflows/judge\.yml@'
```

## Known limits

- Held-out *inputs* (never answers) go to the run job as an artifact, which anyone who can read the
  repository can download for a day. The served count and `stale_after` bound how long a case set is used.
- Every pull request, from anyone, starts a judge run and counts against the case set.
- The merge queue (`merge_group`) is not wired yet; use "require branches to be up to date".
