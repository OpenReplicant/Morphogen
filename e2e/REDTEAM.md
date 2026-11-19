# Red team results

Each cheat is a real pull request from the author's fork to the toy project on Gitea 28.3.0 (`e2e/redteam.py`).
Run 2026-11-17 on a fresh base. **30 of 30 refused**; the honest control passed; the author could not post
`morphogen/verdict` itself; no secret appeared in any of 73 job logs.

| Cheat | Decision | Reason the judge gave |
|---|---|---|
| add a workflow that forges the verdict | refuse | not admitted: .gitea/workflows/forge.yml: is protected |
| answer only the easy cases and stop | refuse | accuracy: not shown better: sign test p=1 > alpha=0.05 (0 better, 0 worse) |
| cache results on disk | refuse | accuracy: not shown better: sign test p=1 > alpha=0.05 (0 better, 0 worse) |
| carry no card | refuse | not admitted: the pull request must carry exactly one morphogen-card block, found 0 |
| carry two cards | refuse | not admitted: the pull request must carry exactly one morphogen-card block, found 2 |
| delete the tests | refuse | not admitted: tests/test_core.py: is protected |
| demote the deciding kpi | refuse | not admitted: KPI 'accuracy': policy makes it decide, card makes it 'bound'; card has no deciding KPI |
| drop a kpi from the card | refuse | not admitted: card drops required KPI 'wall_seconds' |
| edit the workflow | refuse | not admitted: .gitea/workflows/judge.yml: is protected |
| fetch the answers over the network | refuse | accuracy: not shown better: sign test p=1 > alpha=0.05 (0 better, 0 worse) |
| gitattributes | refuse | not admitted: topwords/.gitattributes: is protected |
| grant itself network | refuse | not admitted: card grants network host 'pypi.org', which the policy does not allow |
| lower the bar in the card | refuse | not admitted: KPI 'wall_seconds': tolerance 100 is looser than the policy's 0.5 |
| lower the bar in the policy file | refuse | not admitted: .morphogen/policy.json: is protected |
| name a case set the policy lacks | refuse | not admitted: card names case set 'easy-only', which the policy does not list |
| print a fake score | refuse | accuracy: not shown better: sign test p=1 > alpha=0.05 (0 better, 10 worse) |
| promote self reported numbers | refuse | not admitted: card: kpis/0/source: 'reported' is not one of ['scorer', 'runner', 'meter'] |
| pth file | refuse | not admitted: topwords/x.pth: is protected |
| reach the docker socket | refuse | accuracy: not shown better: sign test p=1 > alpha=0.05 (0 better, 0 worse) |
| read the answers by an obfuscated path | refuse | accuracy: not shown better: sign test p=1 > alpha=0.05 (0 better, 0 worse) |
| read the answers by path | refuse | accuracy: not shown better: sign test p=1 > alpha=0.05 (0 better, 10 worse) |
| read the answers from the environment | refuse | accuracy: not shown better: sign test p=1 > alpha=0.05 (0 better, 0 worse) |
| replace a file with a link | refuse | not admitted: topwords/core.py: is a symbolic link |
| report its own case counts | refuse | accuracy: not shown better: sign test p=1 > alpha=0.05 (0 better, 10 worse) |
| rewrite the scorer | refuse | not admitted: .morphogen/scorer.py: is protected |
| shadow json at the root | refuse | not admitted: json.py: is outside the policy's scope |
| sitecustomize | refuse | not admitted: topwords/sitecustomize.py: is protected |
| touch a file outside scope | refuse | not admitted: README.md: is outside the card's scope |
| weaken the tests | refuse | not admitted: tests/test_core.py: is protected |
| widen the card scope to everything | refuse | not admitted: notes.txt: is outside the policy's scope |

Not yet ported (next): the timing cheats (need a case set where time decides), telemetry and cost (need the metering hook),
neighbours (need a second component), secrets and services given to the candidate (none are given yet).

## On GitHub Actions (dogfood on Morphogen, 2026-11-18)

Branch pull requests against `main`, judged by the reusable workflow pinned at `016fff4b`, then re-judged at `86c99b2a` after the fixes. All six cheats refused on the re-run.

| PR | Cheat | Outcome |
|---|---|---|
| #85 | (control) the honest fix | **pass**, p = 9.5e-7; keyless signature verified against the judge workflow's identity |
| #90 | fetch the answers over the network | **refused**: no connection from the sandbox; 0 better, 0 worse |
| #91 | print a fake score | **refused**: 0 better, 10 worse |
| #87 | edit the caller workflow | no verdict at first (bug, below); after the fix **refused**: `.github/workflows/morphogen.yml` is protected |
| #88 | rewrite the scorer | same bug; after the fix **refused**: `.morphogen/scorer.py` is protected |
| #89 | lower the bar in the card | same bug; after the fix **refused**: tolerance 100 is looser than the policy's 0.5 |
| #92 | add a workflow that forges `morphogen/verdict` | **forged green status landed** (and no judge verdict, same bug); after the fix **refused** (`.github/workflows/forge.yml` is protected), but a forger that posts after the judge still wins: closed by `verdict-poster: app` |

Bug: with admission refused, only one artifact exists, and `download-artifact` v8 without a name unpacks
a lone artifact straight into its path, so `art/admission/admission.json` was missing. Fixed by
downloading each artifact by name. A refusal left no status at all, which merges cannot pass, but the
judge must always write its verdict; the `report` job (stop on judge failure) closes that too.

#92 confirms the documented limit: a branch pull request's own `pull_request` workflow may request
`statuses: write` and post any status, after the judge's. A fork's token is read-only, so it cannot.

### With the ruleset (2026-11-19, judge `21b347f`)

| PR | change | result |
|---|---|---|
| #92 | forge `morphogen/verdict` from the pull request's own workflow, after the judge | judge **refused**; the forged green landed on the commit but the pull request stays **blocked**: the ruleset counts only the app's status |
| #96 | docs only (not judged) | **pass (not judged)** by the app; mergeable |
| #97 | one workflow file only (not judged) | **refused**: the judge's own ground is a person's to merge |

