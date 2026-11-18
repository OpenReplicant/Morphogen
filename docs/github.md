# Set up on GitHub

The judge is a reusable workflow, [`.github/workflows/judge.yml`](../.github/workflows/judge.yml), called
from a short `pull_request_target` workflow in your repository. Because of that trigger, GitHub always
runs the definition on your default branch: a pull request cannot change what judges it.

Everything below is done once by the repository owner, in the GitHub web UI.

## 1. The policy and the scorer

On the default branch, add `.morphogen/policy.json` and `.morphogen/scorer.py` (see
[cards](cards.md#the-policy-held-by-the-owner-on-the-base)). List your workflows, the policy itself and your
tests under `protected` (workflow files and `.morphogen/` are protected whatever the policy says).

## 2. A private repository for the held-out cases

One directory per case set: `<set>/cases.jsonl`, one `{"id", "input", "answer"}` per line. The judge
keeps `<set>/served`, the count of verdicts served. Generate the cases inside Actions if you can, so
the answers never pass through anyone's machine (the dogfood does this:
`morphogen-seed-cases.yml` on `main`).

No private repository? Seal the case sets and keep them in any branch: see `judge/custody.py` and the
`cases-sealed` input.

## 3. A fine-grained token for the case repository

Settings → Developer settings → Fine-grained tokens → Generate new token. Resource owner: the
account that owns the case repository. Repository access: only the case repository. Permissions: **Contents: read and write**
(write is for the served count). Nothing else.

## 4. The judge's GitHub App

This is what makes the `morphogen/verdict` status impossible to forge. Without it, anyone who can run
a workflow in your repository (including a pull request from a branch, not a fork) can post the same
status after the judge (measured: [security](security.md#a-forged-status)).

1. Create the app under **the account that owns the repository**: for a personal account, your
   Settings → Developer settings → GitHub Apps; for an organisation, the organisation's Settings →
   Developer settings → GitHub Apps. Then **New GitHub App**. An app made *Only on this account*
   under a different account cannot be installed on your repository; if that happened, move it with
   the app's Advanced → Transfer ownership.
   - Name: e.g. `Morphogen Judge` (must be unique on GitHub). Homepage URL: your repository.
   - Webhook: **untick Active**.
   - Repository permissions: **Commit statuses: Read and write**. Leave everything else at *No access*.
   - Where can this app be installed: **Only on this account**.
2. On the app's page, note the **Client ID**, then **Generate a private key**: a `.pem` file downloads.
3. **Install App** → only select repositories → your repository.

## 5. The environment

Settings → Environments → **New environment** named `morphogen-judge`.

- Deployment branches: **Selected branches** → your default branch only.
- Environment secrets:

| Secret | Value |
|---|---|
| `MORPHOGEN_CASES_TOKEN` | the token from step 3 |
| `MORPHOGEN_APP_CLIENT_ID` | the app's Client ID |
| `MORPHOGEN_APP_KEY` | the whole contents of the `.pem` file |

Only the judge's `admit`, `score` and `report` jobs name this environment. The job that runs the
candidate cannot read it.

## 6. The caller workflow

Copy [`templates/github/morphogen.yml`](../templates/github/morphogen.yml) to `.github/workflows/`,
replacing `JUDGE_SHA` in both places with the same Morphogen commit, and the case repository and module:

```yaml
name: morphogen
on:
  pull_request_target:
    types: [opened, synchronize, reopened, edited]
permissions: {}
jobs:
  judge:
    uses: OpenReplicant/Morphogen/.github/workflows/judge.yml@JUDGE_SHA
    permissions: {contents: read, statuses: write, id-token: write}
    secrets: inherit
    with: {judge-ref: JUDGE_SHA, cases-repo: OWNER/CASES, module: your_module, verdict-poster: app}
```

| Input | Default | Meaning |
|---|---|---|
| `judge-ref` | (required) | The Morphogen commit; must equal the one in `uses:`. |
| `module` | (required) | The Python module the sandbox runs, `python -I -m`-style. |
| `subdir` | `.` | Where in the repository the module lives. |
| `cases-repo` | this repository | Where the case sets are. |
| `cases-branch` | `main` | |
| `cases-sealed` | `false` | The case sets are sealed under `MORPHOGEN_CASES_KEY`. |
| `verdict-poster` | `actions` | `app` posts the verdict as your GitHub App. Use `app`. |
| `signing` | `keyless` | `keyless`: GitHub's identity, logged publicly by Sigstore. `key`: a cosign key pair in the environment. |
| `sandbox-image` | `python:3.13-slim@sha256:…` | Pinned by digest. |
| `case-timeout` | `60` | Seconds per case. |

## 7. The merge gate

Settings → Rules → Rulesets → **New branch ruleset**, targeting your default branch:

- **Require status checks to pass**: add `morphogen/verdict`, and set its source to your app
  (`Morphogen Judge`), not "any source".
- **Require branches to be up to date before merging**, so each change is judged against the base it
  lands on.
- Block force pushes.

- **Bypass list**: add *Repository admin* (or your maintainers' role), "For pull requests only". This is
  how a person merges a change the judge refuses to decide on (see below).

Every pull request to that branch now needs a passing verdict from the app. The caller has no `paths`
filter, so the judge sees every pull request and decides which kind it is:

| The change touches | Verdict |
|---|---|
| anything in the policy's `scope` | **judged**: needs a card, and passes only on the measurements |
| nothing in the scope, and nothing the judge relies on | **pass (not judged)**: signed, `"judged": false`, nothing run |
| nothing in the scope, but a workflow, `.morphogen/`, a `protected` path, a link or a submodule | **refuse**: the judge never passes a change to its own ground; a person reviews it and merges by bypass |

So put in `scope` or `protected` everything the judged code depends on: a change elsewhere passes
unjudged. A forged `morphogen/verdict` from any other workflow does not satisfy the rule, because its
source is not the app.

## 8. Who may author

Judged changes should come from people (or agents) **without write access**, through forks. Anyone with
write access can push to protected branches' neighbours, re-run workflows and edit settings; the app
stops them forging the verdict, but the trust model assumes authors are outsiders.

## Running it

Open a pull request with a card. The judge's run appears under Actions; its summary shows the verdict
table; the signed verdict is the `verdict` artifact; `morphogen/verdict` appears on the commit.
