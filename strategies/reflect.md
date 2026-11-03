---
name: reflect
description: Learn from failures. Probe the parent, write down why each failing or slow case went wrong, propose edits that each target a different cause, keep the candidates that are best on at least one case, and judge those. After GEPA, ProTeGi, PromptWizard and meta-prompting.
when: The candidate is text or code whose failures can be read and explained, such as a prompt, a rule set or a parser; or a pass is close and the probe shows which cases stand in the way.
weak_when: Failures are noise rather than causes (timing jitter), or the probe shows no failing cases to learn from.
---

# reflect

**Parent:** the tip of the trunk, or the best variant in `archive(target)` when
its probe still shows failing or slow cases.

**Candidates:**
1. `probe` the parent. Collect the failing cases (with expected and actual
   output), the slowest ones, and the reasons on recent failed verdicts.
2. Write a short critique per failure: the cause, in one sentence, citing the
   case. Group cases by cause. This is the "textual gradient".
3. Propose two or three edits, each aimed at a different cause, and smallest
   first. Where examples help (prompts), add or replace examples drawn from
   the failing cases' patterns, never the cases themselves.
4. `probe` each edit. Keep an edit only if it fixes cases of its cause without
   breaking cases that passed before. Among the survivors, keep every one that
   is best on at least one case (a Pareto set), not only the best on average.

**Judging:** `judge` each kept candidate against the trunk. Label it with
`strategy: reflect`, its cause as the family, and its parent.

**After:** propose the best passing candidate. Record each critique with
`evidence_note` (trust `inferred`), citing the probe; a critique that the
verdict contradicted is a lesson for the next round.

**Stop:** after two rounds whose probes fix no new cases.
