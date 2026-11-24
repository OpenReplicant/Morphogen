---
name: research
description: Choose a component, library, service, model or vocabulary from the catalogs instead of from memory - name the role on the map, find options with the catalog skill, test the shortlist against the need, and record the pick. Use when the user needs something picked ("which X should we use", "find a library for", "is there something that does"), or before adding any part, package or image to a system.
---

# Research: a choice made from catalogs, not memory

The `catalog` skill applied to one decision, with the operator's rules on top. What you remember about a tool is a
lead, not evidence: every fact that decides the choice comes from a registry's answer, the tool's documentation
or a trial you ran. Everything is files, on any harness.

## 1. The role and the need, first

Find the role on the map (the `map` skill if the part you need is not mapped yet). Write the need before looking
at options, so options are tested against it rather than the need bent to fit a favourite:

- the interfaces the role requires (the `API` entities it consumes), exactly enough to check;
- what is measured, as a goal with a metric and a target (the system's description, or the cell's `better`);
- the operator's rules for this choice, asked once if not given: licences allowed, how old a release must be,
  where it must run, what it may cost, whether lookups may leave the machine. Treat them as part of the need.

Put the need in one place the options will point at: the description of the role's entity, or a short note file
beside the catalog.

## 2. Options

The `catalog` skill, steps 2 and 3: at least three where there are that many, from more than one catalog, each
as a `Component` with `spec.lifecycle: candidate`, its source, licence and the interfaces its sources say it
provides. Licence, versions and dates come from the registry's answer (deps.dev, GitHub's API, the licence file
when the API says it cannot tell), quoted as evidence. Rule out on the operator's rules early and say which.

## 3. Test the shortlist

Write a trial script in the project (its own folder, e.g. `trials/<slug>/`) that runs every shortlisted option on
the same cases, against real data where there is some, and prints one result line per option and case; keep the
output in a file. Pin every image, jar and package it uses, and fetch with checksums. Test each need, not what is
easy to measure. Record each result on the option's `spec.morphogen.evaluation` with the output file as evidence.

When two or more meet the need and the question is which is better, that is a judge's question: use the
`morphogen` skill where the role is a cell it can judge; otherwise the measurements and your recommendation go to
the operator.

## 4. Record the pick

In a pull request, for the operator to approve:

- the chosen option's `spec.lifecycle` moves from `candidate` to the project's own (and the part's entity points
  at it); rejected options keep their entities as `candidate`, with a note on what would make one the pick;
- where the project keeps a decision log (a file of decisions, ADRs), a new entry: what was chosen and pinned,
  where its docs were read, the options and why the others lost.
