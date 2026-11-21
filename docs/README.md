# Morphogen documentation

Morphogen is a judge for changes. A change lands only with a verdict its author cannot reach: the
author cannot see the held-out cases, cannot edit the rules it is judged by, and cannot report its own
numbers. Authors are often language models optimising against the judge, so the judge assumes every
author will try to cheat, and is built so that cheating fails.

It is built from standard CI parts (a forge's pull requests, its Actions runners, Docker, Sigstore)
plus a few small custom pieces: the card and verdict documents, admission, statistics, and case custody.

| Read this | If you want to |
|---|---|
| [How it works](how-it-works.md) | understand the pipeline and why each part holds what it holds |
| [Set up on GitHub](github.md) | judge pull requests on a GitHub repository |
| [Set up on Gitea](gitea.md) | judge pull requests on a self-hosted forge |
| [Cards, policies and verdicts](cards.md) | write a card, set a policy, read a verdict |
| [The verdict](verdict.md) | read verdicts in another program: the output shape, a contract |
| [Upgrading](upgrading.md) | move a caller to a newer judge commit: required edits and checks |
| [Statistics](statistics.md) | know exactly when a candidate passes |
| [Security](security.md) | see the threat model, what the red team found, and the known limits |

Decisions, with what was rejected and why, are in [`../DECISIONS.md`](../DECISIONS.md). The red team's
results are in [`../e2e/REDTEAM.md`](../e2e/REDTEAM.md).

## Status (2026-11-18)

- **Gitea:** end to end on a live instance. Honest fix passes and merges; 30 of 30 cheats refused.
- **GitHub Actions:** end to end on Morphogen's own pull requests (the `dogfood/` toy). Honest fix
  passes with a keyless-signed verdict; the first cheats are refused. A forged status from a branch
  pull request's own workflow is closed by posting the verdict as a GitHub App (see Security).
- **Not built yet:** the timing red team, the metering hook (model-gateway cost), the merge queue on
  GitHub, the quickstart. Proposed: an adversarial tester (see [How it works](how-it-works.md#next-an-adversary-with-skin-in-failing)).
