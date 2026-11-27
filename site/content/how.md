---
title: How it works
description: Papers report far more gains than anyone tests, mostly once, on setups unlike yours. The research agent keeps a catalog of those claims for this system and tests the promising ones, so that only measured gains reach the code.
kind: page
nav: 90
blocks: [statuses, steering, files]
---

## A research loop with a judge at the end

1. **Watch.** New papers are read for the roles in the system's map and the open questions in its docs. Nothing else.
2. **Read.** Each paper is read far enough to find what it measured, on what, and how. How much was read is recorded
   with every claim.
3. **Catalogue.** A method becomes an option for a role. Each claimed gain becomes a claim: one measure, the
   baseline, the effect if the paper states one, the conditions (models, precision, engine, dataset, runs, who
   measured it), and a verbatim quote that a verifier matches against the source.
4. **Predict.** The claim's conditions are compared with this system's own. The agent writes the probability that
   the finding holds here, and why, before anything is tried.
5. **Test behind the judge.** The cheapest informative trial goes first. An implementer turns the method into a
   change, and Morphogen's judge decides on cases the implementer never saw. A paper's number never decides
   anything.
6. **Score the prediction.** The outcome is recorded against the claim: replicated, did not transfer, or not
   testable here. Predictions written before the outcome are scored, which calibrates the next ones.

## Finding your way around

Every claim, paper, trial, model, option and role has a page, and every page lists what it links to and what links
to it. A model's page lists every claim tested with it and the result; a trial's page lists the claims it gave an
outcome for, and on which models; a claim's page starts with a table of what it was tested on. The
[map](map.html) shows all of it at once, and [search](search.html) finds any of it.
