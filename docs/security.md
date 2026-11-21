# Security

## Threat model

The author of a change wants it to pass, and may be a language model optimising against the judge.
It controls everything in its pull request: code, tests, configuration, workflow files, the card, the
description, and what its program prints. It does not control the protected base branch, the forge's
settings, the held-out cases, or the judge's secrets.

The judge must refuse any change that improves its verdict without improving the thing measured.

## What stops what

| The author tries to | Stopped by |
|---|---|
| change the workflow, the policy, the scorer, the tests | `pull_request_target` runs the base's definition; admission refuses protected paths |
| lower the bar or drop a KPI | the card can only narrow the base's policy |
| report its own numbers | KPIs come only from the scorer, the runtime, or the meter; the schema cannot say otherwise |
| read the answers (environment, paths, network, the Docker socket) | the run job never holds them; the sandbox has no network and no socket |
| answer only easy cases, crash, hang | every case is run and scored; a missing answer is wrong; per-case timeouts |
| memoise or cache across cases and runs | a fresh read-only container per case |
| shadow the interpreter (`sitecustomize`, `.pth`, `json.py`) | `python -I`, the program appended after the standard library, and admission refuses those files |
| replace a file with a link, add a submodule | admission refuses them |
| forge the verdict status | the verdict is posted by the judge's GitHub App, and the ruleset accepts only that app |

## Red-team results

Every cheat is a test that must keep failing. Results: [`../e2e/REDTEAM.md`](../e2e/REDTEAM.md).

- **Gitea:** 30 of 30 refused, as real pull requests from a fork.
- **GitHub:** the first six as branch pull requests on Morphogen; the network and fake-score cheats were
  refused; the rest exposed two problems, both fixed (below).

## Problems found, and their fixes

### A refusal that was never written

On GitHub, when admission refused a change, the score job crashed before writing the refusal (an
artifact-layout difference in `download-artifact` v8). Nothing merged, but no verdict was posted. Fixed
by downloading artifacts by name, and by a `report` job that posts `stop` whenever the judge itself
fails, so a broken judge is never silent.

### A forged status

A pull request from a branch in the same repository can add its own `pull_request` workflow, ask for
`statuses: write`, and post `morphogen/verdict` = success after the judge does. Measured: the forged
status landed (#92). GitHub cannot tell it from the judge's, because both come from the GitHub Actions
app. A fork's token is read-only, so forks cannot do this.

Fix: `verdict-poster: app`. The judge posts as a GitHub App whose key only the judge's environment
holds, and the ruleset requires `morphogen/verdict` from that app. Set up in [GitHub step 4](github.md#4-the-judges-github-app).

### A missing secret hidden by a fallback

The reusable workflow at first fell back to the workflow's own token when the case token was absent,
which turned "the caller did not pass its secrets" into "repository not found". Now a missing secret is
an error that names it.

## Known limits

- **Inputs are visible while the run lasts.** The run job needs the held-out *inputs* (never the answers);
  they travel as an artifact, and on a public repository any signed-in GitHub user can download a run's
  artifacts. The score job deletes the inputs and the run records (whose outputs echo the inputs) as
  soon as it has them, and the report job tries again if scoring failed, so they are exposed for the
  length of the run job (minutes), no longer for a day. This matters most where the input *is* the
  case, as for an environment seed. The served count and `stale_after` bound how long a set is used.
- **Unjudged passes trust the policy's lists.** A change outside `scope` and `protected` passes without
  being run. If the judged code imports something listed in neither, a change to it alters the judged
  system unmeasured. The owner must list dependencies in one or the other.
- **Every pull request costs a judgement.** Anyone can open a pull request and so spend a served count.
- **Docker on the runner host.** On self-hosted runners the untrusted job starts the sandboxes through
  the host's Docker; the candidate's own containers have no socket, but a container escape would reach
  the host. Rootless Podman would close this.
- **The merge queue** is not wired on GitHub yet; "require branches to be up to date" stands in.
- **Timing, partly covered.** Measured and fixed: the judge's own run order made identical code look
  faster (pairs with a coin-flip order now); container start-up dominated wall time (the base's harness
  now times the program itself). Tested: a fake record printed by the program, a patched clock in its own
  process, writing to the harness through `/proc`, a detached grandchild, killing the harness
  (`tests/test_harness.py`). Not yet: doing less work only when timed, memoising within a case, sniffing
  the sandbox. The sandbox's fresh read-only container per case bounds caching across cases.
