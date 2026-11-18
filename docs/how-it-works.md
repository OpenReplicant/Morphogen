# How it works

```
pull request + card ─► admit ─► run (untrusted) ─► score (trusted) ─► signed verdict ─► merge gate
```

## The four stages

1. **Submit.** A change arrives as a pull request. Its description carries a **card**: one sentence
   saying what the change is for, the paths it may touch, the case set it is judged on, and the KPIs it
   must hold to. See [cards](cards.md).
2. **Admit.** Before anything runs, the judge reads the owner's **policy** from the protected base
   branch and checks the card against it (a card may make the bar stricter, never looser) and every
   changed path against both scopes and the protected list. Paths come from `git diff`, never from the
   change's own account. Symbolic links, submodules, workflow files, the judge's own files, and files
   the Python interpreter runs at start-up are always refused. A refused change is never run. A change
   that touches nothing in the policy's scope is **not judged**: it gets a signed pass marked
   `"judged": false`, unless it touches the judge's own ground (workflows, rules, protected paths),
   which the judge refuses and leaves to a person.
3. **Run, untrusted.** The base and the candidate each run on every held-out case's *input* (never its
   answer), one fresh container per case: no network, read-only filesystem, no capabilities, an
   unprivileged user, CPU, memory and process limits. Input on stdin, output on stdout. Wall time comes
   from Docker's own record of when the container started and stopped. This job holds no secrets.
4. **Score, trusted.** A second job, defined only on the base, fetches the held-out answers, scores
   both runs' outputs with the base's scorer, compares candidate against base case by case, and writes
   a **verdict**: pass, refuse or stop. It signs the verdict (Sigstore), attaches it to the run, and
   posts it as the `morphogen/verdict` commit status. Merging requires that status.

## Who holds what

| Job | Runs candidate code | Holds answers | Holds secrets | Token |
|---|---|---|---|---|
| admit | no (reads git objects only) | no (strips them) | case-store token | read |
| run | yes, only inside sandbox containers | no | none | read |
| score | no (reads run records as data) | yes | case-store token, signing identity, verdict poster | read, statuses |
| report | no | no | verdict poster | statuses |

The split is the standard defence against running untrusted code where secrets are, kept strict: the
job that runs the candidate never holds the answers, and the job that holds the answers never runs the
candidate's code.

**Every definition is the base's.** The workflow is triggered by `pull_request_target`, so the forge
runs the definition on the protected branch, whatever the pull request changes. This was measured on
Gitea (a fork's edit to the workflow was ignored) and holds on GitHub by design of the event.

## What decides

Only the judge's own measurements: scores computed in the trusted job on cases the candidate cannot
read, timings from the container runtime, and (soon) cost from the model gateway's meter. Anything the
candidate prints about itself is recorded as reported and never decides. The schema has no way to
declare a self-reported KPI.

## Case custody

Held-out cases live where only the trusted jobs can read them: a private repository (the default), or,
where no private store exists, sealed with AES-256-GCM in any branch with the key held only by the
trusted jobs (`judge/custody.py`). The judge counts how many verdicts each case set has served and
stops judging with it past the policy's `stale_after`.

## Next: an adversary with skin in failing

*Proposed, not built.* Where an optimiser such as GEPA uses a model to improve an artefact, Morphogen
would use a model to try to fail the improvement: it reads the diff and the card (never the held-out
answers), proposes new cases where the candidate might be worse, and the judge checks them. To keep the
adversary honest:

- a proposed case counts only if its expected answer comes from outside the adversary (the base's
  behaviour where nothing should change, a reference, or a checkable property), and the base gets it right;
- the adversary gains only from valid cases the base passes and the candidate fails, so failing
  everything earns nothing;
- A/A: on identical code it must find nothing;
- its cases are written after seeing the candidate, so they can only veto, never pass; the fixed
  held-out set still decides, with its stated statistics;
- every real regression it finds joins the held-out store.
