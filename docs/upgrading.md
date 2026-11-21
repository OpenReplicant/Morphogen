# Upgrading a caller to judge `b921c9b`

For a repository whose `.github/workflows/morphogen.yml` calls Morphogen's reusable judge, pinned at
`99c2ca10abb1cf769cdb47e34d8d7264aae4ef0a` or any later commit up to this one. Target:
**`b921c9b34970d5896cf8e2f1ecd436cf53788444`** (Morphogen `rebuild-8`; its unit and pipeline tests pass).

## 1. Required edits to `morphogen.yml`

Change all three, or every judged pull request ends in `stop`:

```yaml
    uses: OpenReplicant/Morphogen/.github/workflows/judge.yml@b921c9b34970d5896cf8e2f1ecd436cf53788444
    permissions: {contents: read, statuses: write, id-token: write, actions: write}
    with:
      judge-ref: b921c9b34970d5896cf8e2f1ecd436cf53788444
```

`actions: write` is new: the trusted score job uses it to delete the run's held-out inputs and run
records as soon as it has scored them.

This file is a workflow, so the judge refuses the pull request that changes it. The owner merges it with
the ruleset's bypass.

## 2. Check the case sets (before or with the repin)

Every line of every `<set>/cases.jsonl` in the case store must be exactly
`{"id": <non-empty string>, "input": ..., "answer": ...}`, with no other keys and no duplicate ids. Anything
else fails at admission and the verdict is `stop`. Fix the generator, not the file, then reseed.

## 3. Re-set timing tolerances

`wall_seconds` is now measured by the base's harness around the program alone. Container start-up no
longer counts, so values drop a lot (the dogfood toy went from about 0.18 s to about 0.03 s per case).
A `bound` tolerance chosen against the old numbers, in the policy's `required_kpis` and in cards, is now
much looser in relative terms. Re-set it from a fresh judged run.

There is a new runner KPI, `cpu_seconds`: the program's user plus system CPU time, as the kernel counts
it. A policy may require it, or allow it with `allowed_kpis: [{"name": "cpu_seconds", "source": "runner"}]`.
It is steadier than wall time under a busy machine.

## 4. How the program now runs (check that nothing relies on the old way)

- **It runs as a child of the base's harness**, not as the container's main process: `python -I`, the
  work tree at `/work` placed after the standard library, the case JSON on stdin, its stdout as the
  output. As before: no network, read-only root, `/tmp` writable (16 MB), user 65534, `HOME=/tmp`.
- **Its working directory is always `/work`.** Before, it was the image's `WORKDIR`.
- **The harness enforces the case timeout** (`case-timeout`), and kills anything the program left running
  when it exits.
- **A base may supply its own harness** at `.morphogen/harness.py`. It is always protected, and is used in
  place of the judge's own if present. Its contract: read the case on stdin, run the candidate as a
  separate process, and write exactly one line of JSON with exactly these keys: `exit` (int),
  `timed_out` (bool), `wall_seconds` and `cpu_seconds` (numbers ≥ 0), `output` and `stderr_tail`
  (strings). `output` is what the scorer receives. The candidate's process must never be able to write
  that line (Morphogen's `CLAUDE.md`, rail 1: the measurer and the measured run apart). A project whose
  environment runs inside the candidate's process should move to this.

## 5. Optional: judge every pull request

If the caller drops its `on.pull_request_target.paths` filter, the judge sees every pull request:

- changes touching the policy's `scope` are judged as before;
- changes outside it get a signed pass marked `"judged": false`, with nothing run;
- changes outside it that touch a workflow, `.morphogen/`, a `protected` path, a link or a submodule are
  refused, for a person to merge with the bypass.

Then the ruleset can require `morphogen/verdict` from the judge's GitHub App on the whole default branch.
With the filter kept, nothing changes.

## 6. What else is different

- **Artifacts:** a run's `inputs` and `runs` artifacts are deleted once scored. `admission` holds only the
  card and admission's reasons. Only `admission` and `verdict` remain afterwards. Per-case outputs are no
  longer downloadable.
- **Run summary text** now opens with the verdict in plain words. Parse `verdict.json`, never the summary.
- **Verdict JSON** (the contract, `docs/verdict.md`): unchanged except the optional `"judged": false`.
  KPI names such as `cpu_seconds` are data, not schema.
- **Run order:** base and candidate run case by case, the order in each pair by coin flip. Nothing to do.
- **Served count:** concurrent verdicts no longer lose counts (a same-second race made identical commits).

## 7. Verify after the repin

On the first judged pull request:

1. The score job's log shows `artifact … removed (204)` twice.
2. The run's artifact list shows only `admission` and `verdict`.
3. The `morphogen/verdict` status is posted by the judge's app, and the summary opens with plain words.
4. `verdict.json` has a `cpu_seconds` entry only if the policy or card asks for it, and `wall_seconds`
   values are on the new, smaller scale.

If any of these fails, delete the run's artifacts by hand and report it to Morphogen.
