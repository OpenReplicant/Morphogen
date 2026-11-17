# Morphogen (rebuild 8)

A judge for changes, built from standard CI parts. A change lands only with a verdict its author cannot
reach: the author cannot see the held-out cases, edit the rules it is judged by, or report its own numbers.

```
pull request + card ──► admit ──► run untrusted ──► score trusted ──► signed verdict ──► merge gate
   (from a fork)        (base's    (sandbox per     (base's scorer,   (cosign bundle,    (required status
                        policy)    case, no net)    held-out answers)  JSON Schema)       morphogen/verdict)
```

- `schemas/`: the card (what a change is for, may touch, must hold to), the owner's policy (held on the
  base; a card may only narrow it), and the verdict. JSON Schema 2020-12.
- `judge/`: the custom parts. `admit.py` (paths against scope, card against policy), `run.py` (untrusted
  harness), `score.py` (trusted scoring), `stats.py` (paired sign test, bootstrap bounds, MDE), `verdict.py`.
- `e2e/`: a real Gitea, two Gitea Runners, a toy project, and the red team as pull requests from a fork.
- `DECISIONS.md`: what was chosen, what was rejected, and what was measured.

```bash
pip install -e '.[test]' && pytest -q          # schemas, admission, statistics, A/A
```

See `e2e/README.md` for the end-to-end run.
