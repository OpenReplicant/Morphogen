# Cards, policies and verdicts

Three versioned JSON documents, specified as JSON Schema 2020-12 in [`../schemas/`](../schemas/).
They are the whole interface: a card in, a signed verdict out.

## The card (written by the author)

Carried in the pull request description as exactly one fenced block tagged `morphogen-card`:

````markdown
```morphogen-card
{"card": "morphogen.card/v1",
 "intent": "Count words case-insensitively so top_words matches the reference on mixed-case text.",
 "scope": ["dogfood/topwords/core.py"],
 "cases": {"set": "topwords-heldout"},
 "kpis": [{"name": "accuracy", "source": "scorer", "direction": "higher", "floor": 0.0, "role": "decide"},
          {"name": "wall_seconds", "source": "runner", "direction": "lower", "floor": 0.5, "role": "bound"}],
 "tests": {"must_pass": ["easy-*"], "must_not_change": []}}
```
````

| Field | Meaning |
|---|---|
| `intent` | One sentence a person can check against the diff. |
| `scope` | Globs for the paths the change may add, modify or delete (`*` within a path segment, `**` across). |
| `cases` | The held-out case set to be judged on, by name. Never the cases themselves. |
| `kpis` | Each with `source` (`scorer`, `runner` or `meter`: who measures it), `direction`, `role` and `floor`. |
| `tests` | Case ids (or prefixes ending in `*`) that must be right, and that must not change from the base. |
| `network` | Hosts the run may reach. Absent: none. Each must be allowed by the policy. |

A **deciding** KPI must improve: `floor` is the smallest mean per-case improvement that counts. A
**bounding** KPI must not get worse: `floor` is the largest mean per-case worsening tolerated.

## The policy (held by the owner, on the base)

`.morphogen/policy.json` on the protected branch. Admission reads it only from there.

```json
{"policy": "morphogen.policy/v1",
 "scope": ["dogfood/topwords/**"],
 "protected": ["dogfood/README.md", "tests/**"],
 "case_sets": {"topwords-heldout": {
   "required_kpis": [
     {"name": "accuracy", "source": "scorer", "direction": "higher", "floor": 0.0, "role": "decide"},
     {"name": "wall_seconds", "source": "runner", "direction": "lower", "floor": 0.5, "role": "bound"}],
   "stale_after": 200}},
 "network": [],
 "alpha": 0.05}
```

`scope` also decides **whether a change is judged at all**: a pull request that touches nothing in it
gets a signed pass with `"judged": false` and nothing run, unless it touches a workflow, `.morphogen/`, a
`protected` path, a link or a submodule, which is refused for a person to merge
([github](github.md#7-the-merge-gate)). So everything the judged code depends on belongs in `scope` or
`protected`.

A card is refused if it drops a required KPI, changes its source or direction, demotes a deciding KPI,
sets a lower floor or a looser bound, adds a KPI the policy does not allow, names a case set the
policy does not list, or grants a host the policy does not allow.

Next to the policy, `.morphogen/scorer.py` defines `score(input, answer, output)`, returning
`{"correct": bool, <kpi>: number, ...}`. `output` is the program's stdout, or `None` if it failed.

## The verdict (written by the judge)

The full shape, field by field, is the contract in [verdict](verdict.md); this section is a summary.

A JSON document attached to the judge's run as the `verdict` artifact, with a Sigstore bundle beside
it. Its main fields:

| Field | Meaning |
|---|---|
| `decision` | `pass` (may merge), `refuse` (may not), or `stop` (the judge could not judge: never a pass). |
| `reason` | Why, in one line. |
| `base`, `candidate`, `judge` | The commits judged and the base the rules were read from. |
| `card_sha256`, `policy_sha256` | Hashes of the exact card and policy (canonical JSON). |
| `cases` | The set, how many cases it has, how many verdicts it has served, whether it is stale. |
| `kpis[]` | Per KPI: cases expected and seen in each run, both means, better / worse / tied counts, the effect, its bounds, the sign test's p, the minimum detectable effect, and the result. |
| `reported` | Anything the candidate claimed about itself. Recorded; never decides. |
| `seed` | The trusted job's own seed for the bootstrap, so the verdict can be recomputed. |

The forge's checks view shows the same verdict as a table in the run summary.

### Checking a verdict yourself

Download the `verdict` artifact from the run linked by the `morphogen/verdict` status, then, for a
keyless (GitHub) verdict:

```bash
cosign verify-blob --bundle verdict.sigstore.json verdict.json \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  --certificate-identity-regexp '^https://github.com/OpenReplicant/Morphogen/\.github/workflows/judge\.yml@'
```

For a key-signed (Gitea) verdict:

```bash
cosign verify-blob --key judge.pub --bundle verdict.sigstore.json --insecure-ignore-tlog=true verdict.json
```
