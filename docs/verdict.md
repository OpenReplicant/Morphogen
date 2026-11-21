# The verdict: its output shape (a contract)

This page explains the verdict's shape. The normative form is the JSON Schema
[`schemas/verdict.v1.json`](../schemas/verdict.v1.json); where this page and the schema differ, the schema is
right and this page is a bug. Readers outside this repository depend on this shape, so **any change to it is a
breaking change**: a new schema version (`morphogen.verdict/v2`), agreed with those readers and landed with
their matching change (`CLAUDE.md`, "Rails").

## What a verdict is

One judgment of one candidate commit against one base commit, on one held-out case set, from the judge's own
measurements only. It answers: is the candidate **better**, **worse** or **the same** as the base, per KPI and
overall, and how sure is it.

## The bytes, the signature and where it lives

- **Encoding:** UTF-8 JSON in canonical form: keys sorted, no whitespace, finite numbers only
  (`judge.schemas.canonical`). Those exact bytes are what is hashed and signed.
- **Signature:** a Sigstore bundle (`verdict.sigstore.json`) beside the document, never inside it. On GitHub it
  is keyless, issued to the judge workflow's identity and logged publicly; on a self-hosted forge, a cosign key.
- **Where:** the `verdict` artifact of the judge's run, which the `morphogen/verdict` commit status links to.
- **Example:** [`examples/verdict.json`](../examples/verdict.json), checked against the schema by the tests.

## Top-level fields

All fields are required unless marked *optional*. No other fields are allowed (`additionalProperties: false`).

| Field | Type | Meaning |
|---|---|---|
| `verdict` | const `"morphogen.verdict/v1"` | The schema version. Readers dispatch on it. |
| `repository` | string | The repository judged, `owner/name`. |
| `pull_request` | integer, *optional* | The pull request number, when there is one. |
| `base` | commit id | The commit the candidate is compared against. |
| `candidate` | commit id | The commit judged. The status is posted on this commit. |
| `judge` | commit id | The base commit the rules (policy, scorer, harness) were read from. |
| `card_sha256` | sha256 hex | Hash of the canonical card: what the change claimed it was for and would hold to. |
| `policy_sha256` | sha256 hex | Hash of the canonical policy the card was checked against. |
| `cases` | object | The case set used; see below. |
| `alpha` | number, 0 < alpha ≤ 0.2 | One-sided significance level for each deciding KPI. |
| `seed` | integer | The trusted job's seed for the bootstrap, so the verdict can be recomputed from the run records. |
| `kpis` | array of KPI results | One per KPI on the card; empty when nothing was measured. See below. |
| `tests` | object, *optional* | Must-pass and must-not-change results; absent when the change was refused before running. |
| `judged` | boolean, *optional* | `false`: the change touched nothing in the policy's scope, so nothing was measured, and a `pass` means only "outside what the judge judges". Absent means `true`. |
| `reported` | object | Numbers the candidate printed about itself. Recorded, never deciding. |
| `decision` | `"pass"` \| `"refuse"` \| `"stop"` | `pass`: may merge. `refuse`: may not (the candidate's fault, or it was not admitted). `stop`: the judge could not judge (the base's run was short, the case set is stale, or the judge failed); neither a pass nor the candidate's fault. |
| `reason` | string, 1–2000 chars | One line a person can read: the deciding KPI's reason, or why it was refused or stopped. |
| `issued_at` | RFC 3339 date-time, UTC | When the judge wrote it. |

Commit ids are 40 hex characters (SHA-1) or 64 (SHA-256 repositories).

### `cases`

| Field | Type | Meaning |
|---|---|---|
| `set` | string | The case set's name; `""` when no case set was used (refused before running, or not judged). |
| `version` | string | The set's version, if the card named one; `""` otherwise. |
| `expected` | integer ≥ 0 | How many cases the set has, so how many each run should have produced. |
| `served` | integer ≥ 0 | Verdicts this set has served, this one included; `0` when no case was served. |
| `stale` | boolean | The set has served more verdicts than its policy allows. A stale set stops the judgment. |

## A KPI result: what each measurement carries

Each entry of `kpis` is one measurement of one metric, on one case set, comparing candidate against base case by
case.

| Field | Type | Meaning |
|---|---|---|
| `name` | string | The metric, as the card and policy name it (for example `accuracy`, `wall_seconds`). |
| `source` | `"scorer"` \| `"runner"` \| `"meter"` | Who measured it: the base's scorer on the outputs, the runner's harness, or the external cost meter. Never the candidate. |
| `direction` | `"higher"` \| `"lower"` | Which way is better. |
| `role` | `"decide"` \| `"bound"` | `decide`: the candidate must be better. `bound`: it must not be worse by more than `floor`. |
| `floor` | number ≥ 0 | For `decide`, the smallest improvement that counts; for `bound`, the tolerance in the metric's units. |
| `expected` | integer | Cases each run should have produced for this KPI. |
| `base`, `candidate` | `{seen: integer, mean: number \| null}` | Per side: cases actually measured, and the mean value (`null` when none). |
| `paired` | `{n, better, worse, tied}`, integers | Cases measured on both sides, and how many the candidate was better, worse, or the same on. |
| `effect` | number \| null | Mean per-case improvement, signed so **positive is better** whatever the direction. |
| `interval` | `[lower, upper]` \| null | One-sided bounds on `effect` at confidence 1 − alpha (paired bootstrap). |
| `p_value` | number \| null | One-sided exact sign test; the null hypothesis is "no better per case". |
| `mde` | number \| null | The minimum detectable effect, stated from the case count before running. |
| `method` | string | The tests used, in words. |
| `result` | `"pass"` \| `"refuse"` \| `"stop"` | This KPI's own outcome. |
| `reason` | string, *optional* | Why, in one line. |

**Better, worse or the same.** Per case: `paired.better`, `paired.worse`, `paired.tied`. Per KPI: `result`
(`pass` for a deciding KPI means better; for a bound, not worse beyond `floor`) with `effect` and `interval`.
Overall: `decision`.

### `tests`

`must_pass` and `must_not_change`, each `{checked: integer, failed: [case id, ...]}`, at most 50 ids listed.

## Mapping for readers (informative)

Not part of the contract, but the reading this shape was written for:

- **Provenance:** the verdict is generated by the judge at commit `judge`, using commits `base` and `candidate`,
  the card (`card_sha256`) and the policy (`policy_sha256`), at `issued_at`; the bundle attests who generated it.
- **Measurements:** each `kpis` entry is a quality measurement of metric `name`, computed by `source`, on the
  case set `cases.set` (`cases.version`), for the candidate *against* the base, with `effect`, `interval` and
  `p_value` as its value and uncertainty, and `result` as better, worse or the same.
- **Goal:** the card's intent (by `card_sha256`) is what the change was for.

## History of v1

- 2026-11-17: first published.
- 2026-11-18: optional `judged` added (DECISIONS.md row 25). This predates the contract rule; a strict reader
  written before it would reject verdicts of unjudged changes. From now on, additions go in a new version.
