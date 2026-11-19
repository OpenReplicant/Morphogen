# Morphogen (rebuild 8)

Morphogen is a judge for changes, built from standard CI parts. A change lands only with a verdict its author
cannot reach: the author cannot see the held-out cases, edit the rules it is judged by, or report its own
numbers. The author is often an LLM optimizing against the judge, so assume it will try to cheat, and design so
that cheating fails.

This branch starts from nothing. Earlier builds are on `main` (rebuild 7) and the `rebuild-*` branches. Read them
for **what they catch**, mostly `tests/test_redteam.py` on `main`. Don't use them for how they are built: this
rebuild does not port their structure, their cell format, or their modules.

## What it is

The pipeline has four stages, each a standard CI piece except where marked:

1. **Submit.** A change arrives as a pull request (or a pushed branch) on a forge the judge controls. It
   carries a **card**: what the change is for, what it may touch, what it must hold to.
2. **Admit** (custom, small). The changed files must lie inside the card's scope, and the rules, scorers,
   cases and workflow come from the protected base branch, never from the change. Anything outside scope is
   refused before anything runs.
3. **Run untrusted.** The candidate and the base each run in a job container with no network beyond what the
   card grants, no secrets, and resources measured by the runner, not by the job. Each case's output is
   uploaded as an artifact.
4. **Score trusted** (the statistics are custom, small). A second job, started after the first and defined
   only on the base, fetches the held-out cases and answers, scores both runs' outputs in its own process, and
   compares candidate against base case by case. It writes a **verdict**, signs it, and posts it as a check run.
   Merging is gated on that check.

The two-stage split is the standard defence against running untrusted code where secrets are. Keep it strict:
the job that runs the candidate never holds the answers, and the job that holds the answers never runs the
candidate's code.

## The custom parts (keep them small)

Everything else is chosen, not built. The custom code is only:

- **The card schema.** Fields: `intent` (one sentence a person can check), `scope` (paths it may change),
  `cases` (a reference to held-out cases, never the cases themselves), `kpis` (each with a direction, a
  floor, and whether it decides or only bounds), `tests` (cases it must pass, and cases where it must change
  nothing). It is versioned and documented as JSON Schema.
- **The verdict schema:** base and candidate commits, the card's hash, per-KPI results with case counts seen
  and expected, the smallest effect the case set could detect, pass or refuse, and the reason. JSON, signed.
- **Admission:** changed paths against scope, with rules read from the base.
- **Statistics:** paired per-case comparison of candidate and base. State the minimum detectable effect
  before running. Use a sign test or bootstrap for paired outcomes, corrected for any extend-while-undecided
  rule. A run whose scorer saw fewer cases than expected is refused: if the candidate's run is short, the
  candidate is refused; if the base's run is short, the judgment stops.
- **Case custody:** held-out cases live where only the trusted job can read them. Count how many verdicts
  each case set has served, and flag it when stale.
- **Metering hook:** a step that reads an external meter (a model gateway's record of tokens and cost) for
  the run, so a candidate cannot report its own cost.

If a part grows past a few hundred lines, stop and ask whether a standard tool already does it.

## Parts to choose, not build

Choose each from current sources: compare candidates, test the shortlist, and record the pick and the
rejections in `DECISIONS.md`.

- **Forge and runner:** self-hosted for local GPUs (candidates: Gitea, Forgejo, Woodpecker CI), and GitHub
  Actions for public projects. A self-hosted runner must never run a public repository's pull requests.
- **Eval runner:** candidates are Inspect AI, promptfoo, DeepEval and pytest. Per-case results go out in a
  standard format (JUnit XML, or the runner's own log).
- **Sandbox:** the runner's job container (Podman by default), with no network unless the card grants a host.
- **Signing and attestation:** in-toto/SLSA via Sigstore (cosign), or the forge's own attestations.
- **Merge order:** the forge's merge queue, so the base advances one judged change at a time.

## What the judge must refuse (the red team)

Every one of these is a test, written before the fix, and must keep failing. The share that fail is the
judge's own metric. Port the cases from `main`'s `tests/test_redteam.py`, re-expressed against this pipeline:

- **Timing:** patch the timer; print a fake measurement; rig the benchmark; do less work only when timed;
  memoize within a run; cache results on disk across runs; sniff the benchmark environment; swap the input.
- **Rules:** lower the bar or edit KPIs in a file the change controls; delete or weaken tests or contract
  tests; drop an interface from the structure; change an owner-held setting (directly, by a later assignment,
  behind an expression); raise the trial budget or swap the sandbox in the working copy; touch a file outside
  scope; replace a file with a link.
- **Interpreter:** shadow standard-library or harness modules (`json.py`, `unittest`, a package);
  `sitecustomize`; `.pth` files.
- **Scoring:** print a fake score; rewrite the scorer; read the held-out answers (from the environment, by
  path, by an obfuscated path); put answers in the inputs; answer only the easy cases and stop; report its own
  case counts.
- **Telemetry and cost:** rewrite the observer; promote self-reported telemetry; switch telemetry off; report
  negative cost; call around the gateway or with a key of its own.
- **Neighbours:** improve its own part while breaking a neighbour's interface or the system's promise, or
  while slowing the whole system.
- **Secrets and services:** print a value it was given (plainly, encoded, in an error message); read a value
  it was not given; commit values; leave state in a service for the next run; reach past the services it was
  given.
- **CI itself:** edit the workflow in the change; run the candidate in the trusted job; read secrets from an
  untrusted job; trigger the trusted job on the candidate's definition.

## The adversary (the direction after the quickstart)

Where an optimizer such as GEPA uses a model to improve an artifact, Morphogen uses a model to try to
fail the improvement. The adversary has no stake in a pass; it gains only by finding valid cases where
the candidate is worse than the base, and every real regression it finds makes the held-out store
better. It is a client of the judge, like an optimizer, and its findings are evidence only once the
judge has run and measured them. Keep it honest:

- **It never sees the held-out cases or answers.** It reads the card and the diff, as data. The diff is
  the author's text and may try to talk to it; that can only make it find less, never pass a change.
- **Its expected answers come from outside it:** the base's own behaviour where the card says nothing
  should change, a reference, or a property the judge can check. A case counts only if the base gets it
  right.
- **It can only veto.** The fixed held-out set, with its stated statistics, decides a pass. A case the
  adversary chose after seeing the candidate is a hypothesis: for deterministic programs one confirmed
  regression is enough; for stochastic ones it is confirmed on fresh draws the adversary did not choose.
- **A/A:** on identical code it must find nothing; record how often it does.
- **What it finds joins the held-out store**, through custody, so case sets renew instead of going stale.
- Its model calls go through the metering hook, and it holds no secrets.

## Rules

- **Look it up, then pin it.** Read a tool's current docs before designing around it. Pin exact versions,
  preferring releases at least two weeks old, and record what you pinned and where you read it. Say what you
  could not check.
- **Red team first.** Any way to cheat goes into the red-team tests before the fix.
- **Only the judge's measurements decide.** Use the runner's timing, the external meter, and scores computed
  outside the candidate on cases it cannot read. Numbers the candidate prints are recorded as reported and
  never decide.
- **A/A after any change to the statistics:** identical code must not pass. Run enough trials to say how
  often it would, and record the rate.
- **Licences:** permissive or LGPL in the default pipeline. A copyleft part (Forgejo is GPL-3.0) needs the
  owner's decision.
- **No optimizers, maps, catalogs or web UI in the judge.** An optimizer is a client that opens pull requests.
  The forge's checks view is the UI.
- **Consumers are generic.** Substrate is the first one (its distilled components arrive as pull requests with
  cards), but nothing here imports from or names a consumer. The interface is the card in and the signed
  verdict out.
- **Changes reach `main` by pull request.** Before merging, check that GitHub shows the head you pushed.
- **Decisions** go in `DECISIONS.md` as new rows (append-only: supersede, never edit).

## Working with the owner

Recommend one option and keep moving. Ask only for decisions that are the owner's: licences, changes to what
the judge accepts as evidence, spending money, publishing. Use plain words.

## Order of work

1. The card and verdict schemas, with examples and validation tests.
2. Choose the forge, runner and eval runner (record candidates, the test, and the pick).
3. A toy project with one KPI, wired end to end: submit, admit, run untrusted, score trusted, a signed verdict,
   a merge gated on it.
4. Port the red team, one cheat at a time, each failing before its fix and after.
5. The statistics step, with A/A runs and the minimum detectable effect stated.
6. Case custody and staleness; the metering hook.
7. A quickstart: "an agent, a case set, is this pull request better" in ten lines, and a verdict a customer can
   read.
8. The adversary (above): first on the toy, with its own A/A and red team, then on a consumer.