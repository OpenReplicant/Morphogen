---
name: catalog
description: Find alternatives for a role a part plays - search the catalogs (package registries, vendors, parts lists, directories) for options that provide the interfaces the role requires, write each as a candidate entity file with its source, and set up how the options will be measured against the system's goals. Use when the user asks what else could do a part's job, whether something better exists, or what to replace a part with; after the map skill has named the role.
---

# Catalog: what else could fill a role

Works on a role the `map` skill named, in files: no database, any harness. An option for a role is an ordinary
Backstage `Component` with `spec.lifecycle: candidate`; what Morphogen adds goes under the one key
`spec.morphogen` (draft schema: `schemas/morphogen-spec.v0.json`). An option is *an alternative* when it
provides every interface the role requires, which is why a loosely named interface makes everything look
interchangeable.

## 1. Read the role

Read the entity that plays the role and the `API` entities it consumes: those are the interfaces any option must
provide. If the role requires no named interface, that comes first (the `map` skill): without one, everything
and nothing is an alternative. Read the system's goals (its description, the cell's `better`): they say which
options are worth measuring. Write the need down before looking, so options are tested against it and the need is
not bent to fit a favourite.

## 2. Search more than one catalog

A catalog here is any place that lists options: a package registry (PyPI, npm, crates.io), a container registry,
GitHub, deps.dev, a vendor's range, a standards body's list, a directory of services or people. Search by need and
topic, not by the name you expect; what you remember is a lead, not evidence. Use whatever the harness reaches: a
web search, a registry's API, `gh api -X GET search/repositories -f q="topic:TOPIC" -f sort=stars`, deps.dev for a
package's versions and licence, `podman search --list-tags REGISTRY/NAME` for images, or an MCP server you are
given. Rule out early on hard limits the operator gave (a licence, a release age, where it runs) and say which,
with the source quoted.

## 3. Write each option with what its source says

One entity per option, in the project's catalog folder:

```yaml
apiVersion: backstage.io/v1alpha1
kind: Component
metadata:
  name: option-name
  description: One line: what it is.
  annotations:
    morphogen.dev/evidence: |
      stated | https://example.org/docs#interfaces | "quoted text of the source"
spec:
  type: library
  lifecycle: candidate
  owner: group:default/team
  providesApis: [the-api-the-role-requires]    # only where a source says so
  morphogen:
    fills: component:default/the-part          # the part or role it could fill
    parameters:                                 # JSON Schema of its adjustable settings
      type: object
      properties:
        batch_size: {type: integer, minimum: 1, maximum: 512}
    licence: MIT
    docs:
      url: https://example.org/docs
      path: docs/option-name/index.md          # only once fetched into markdown
    evaluation: {}                              # filled in step 4
```

- `providesApis` only where a source says the option provides it, with that source's words in the evidence. An
  option that might provide an interface but no source says so: leave it out and note what would settle it.
- `parameters` is what a tuner may move, with its bounds from the docs; a cell that uses the option has its
  settings checked against it. Leave it out when you do not know.
- `licence` and versions come from the registry's answer or the licence file, quoted as evidence, never written
  from memory.
- `docs.url` is the documentation; when a documentation server is available (one that fetches web documentation
  into markdown files), fetch the pages that matter into a folder beside the catalog and give `docs.path`.
  Fetch only what the choice needs, and say which server you used.

## 4. Measure, then judge

Keep the options that fit. Measuring is a trial on the same cases for each option and for what fills the role
now, against real data where there is some: a script that prints one line per option and case, its output kept in
a file as the source. Record it on the option under `spec.morphogen.evaluation`: the need, the method (cases,
command, where the output is), the result and the evidence.

Whether an option is *better* is a judge's verdict, not yours. When the role is a cell the judge can judge
(a `run`, a `better`, tests), use the `morphogen` skill: `measure` the incumbent, put the option on a branch,
`judge` it. Otherwise tell the operator the measurements and say what you would pick and why; the decision is
theirs.

## 5. Report

The options that fit, the ones ruled out and why, the measurements, and what you recommend. A change to the
system (a part replaced) is the operator's to approve: once they decide, change the entity for the part and set
the chosen option's `spec.lifecycle` to match, in a pull request. Never change a verdict or another person's
claim yourself.
