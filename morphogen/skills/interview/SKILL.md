---
name: interview
description: Use when a person describes a software system they want Morphogen to run (its services, what each runs, who calls whom, its settings and limits) and you are to record it in the Knowledge Kernel as a system map, ask about what the map still lacks, and propose its compose file once nothing is missing.
---

# Interviewing a person to describe a system

You talk with a person and record what they say as **extracted** claims about the system: its services, the image
each runs, who calls whom, settings, and the limits they care about. You use the terms encoder-compose uses for
a compose file, so a described system and a running one are one map. Each claim cites the message it came
from and quotes the person's exact words. Then you ask about what the map still lacks. You write through the
knowledge-kernel MCP tools under your own identity (the kernel's write rules apply: one change set per message).

Adapted from rebuild 4's interview skill (organisations and processes) for systems (R5-29).

## The conversation is recorded first

Each message (yours and theirs) is recorded by the **interview encoder** before you cite it: append it to the
interview's chat file (one JSON line: `{"id", "conversation", "author", "kind": "person" | "agent", "time",
"text"}`) and run `python3 -m interview_encoder --source <system> <file>`. The intake filter runs first: a line
holding a secret is left out and reported, so never ask for passwords or keys, and if the person gives one, say it
was not recorded. The person's message is then `urn:kk:message:<source>:<conversation>:<id>`, an `as:Note` whose
`as:content` is their text, recorded by the encoder, not by you. You cite it, so the quote verifier can check
your quote against it (no method verifies its own output).

## IRIs and terms

`<KKT>` is `https://w3id.org/knowledge-kernel/tosca#`, `<BBO>` is `https://www.irit.fr/recherches/MELODI/ontologies/BBO#`,
`<SOSA>` is `http://www.w3.org/ns/sosa/`. Names are lower case, words joined by `-`.

| The person says | Claims |
| --- | --- |
| the system ("a small notes app") | `urn:kk:system:<name>` a `<KKT>ServiceTemplate`; `rdfs:label` "<name>" |
| a service ("a web frontend", "an API", "Postgres") | `urn:kk:node:<name>:<service>` a `<KKT>NodeTemplate`; `rdfs:label`; `<KKT>memberOf` the system |
| what it runs ("the API is ghcr.io/example/notes-api:1.4.2") | `<service>` `<KKT>propertyValue` "<image>" with qualifier `<KKT>propertyName` (written out in full): `image` |
| a setting ("run the API with LOG_LEVEL set to info") | `<service>` `<KKT>propertyValue` "<value>" with qualifier `<KKT>propertyName`: the variable's name (`command` for a command) |
| who calls whom ("the frontend calls the API", "keeps its notes in Postgres") | `<caller>` `<KKT>connectsTo` `<callee>` |
| a limit ("pages within 300 ms on average") | `<service>` `<BBO>maxValue` <number, in seconds for times> with qualifier `<SOSA>observedProperty`: `urn:kk:property:latency-seconds-mean` (no other qualifier: a qualifier more makes it a plan's prediction) |

Look before you mint: `query_claims(predicate="kkt:memberOf", object_entity="urn:kk:system:<name>")` and reuse a
service IRI that names the same thing. Record only what the person said: an image, a version or a setting they
did not give is a question, not a guess.

## Every claim

- `evidence_type: extracted`, one reference `{"source_uri": "<message IRI>", "quote": "<their exact words>"}`. The
  quote is copied from that one message, not paraphrased and not joined across messages.
- What you conclude rather than hear (two names are one service) is `inferred`, with `derived_from` the claims it
  rests on, in `"lane": "review"`: a person confirms it.
- Target scope `urn:kk:scope:default` unless the conversation is restricted.
- One change set per message you record from, idempotency key `interview:<system>|<message IRI>`. The key makes a
  resubmission a no-op, so a corrected change set for the same message takes the key with `|2`, `|3`, ... added.

A change set in the kernel's format (`kernel/schemas/change_set.schema.json`); `generated_by` is the run you
started, `attributed_to` your own agent (`whoami`). Ops are `add_claim`; the object is `{"entity": "<IRI>"}` or
`{"value": {"@value": <text or number>}}`. Predicates and objects may use the kernel's prefixes (`rdf:`, `rdfs:`,
`prov:`, `oa:`, `kkt:`, ...); anything else is a full IRI. **Qualifier keys are stored exactly as written, never
expanded: always write them as full IRIs**, or the claim is recorded but nothing that reads it will find it:

```json
{"idempotency_key": "interview:notes|urn:kk:message:notes:notes-intake:4",
 "attributed_to": "<your agent IRI>", "generated_by": "<your run id>", "target_scope": "urn:kk:scope:default",
 "ops": [
  {"op": "add_claim", "subject": "urn:kk:node:notes:api", "predicate": "rdf:type", "object": {"entity": "kkt:NodeTemplate"},
   "evidence_type": "extracted", "references": [{"source_uri": "urn:kk:message:notes:notes-intake:2", "quote": "which calls an API"}]},
  {"op": "add_claim", "subject": "urn:kk:node:notes:api", "predicate": "kkt:propertyValue",
   "object": {"value": {"@value": "ghcr.io/example/notes-api:1.4.2"}}, "qualifiers": {"https://w3id.org/knowledge-kernel/tosca#propertyName": "image"},
   "evidence_type": "extracted", "references": [{"source_uri": "urn:kk:message:notes:notes-intake:4", "quote": "the API is ghcr.io/example/notes-api:1.4.2"}]},
  {"op": "add_claim", "subject": "urn:kk:node:notes:web", "predicate": "https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue",
   "object": {"value": {"@value": 0.3}}, "qualifiers": {"http://www.w3.org/ns/sosa/observedProperty": "urn:kk:property:latency-seconds-mean"},
   "evidence_type": "extracted", "references": [{"source_uri": "urn:kk:message:notes:notes-intake:6", "quote": "within 300 ms on average"}]}]}
```

(Each op quotes the message it came from; in a real change set all ops quote the one message the set is for.)

## Ask next about the gaps

The gap finder lists what the map lacks, as questions: `query_claims(predicate="oa:hasTarget")` from
`urn:kk:agent:map-gaps`, then `get_entity(<gap>)` for its kind and its question (`oa:bodyValue`). Kinds:
`unknown-peer` (a service calls something not on the map), `no-image` (what runs a service), `unconnected` (how a
service fits with the rest), `no-limit` (how long the service people use may take before something should
change). Ask about one or two at a time, in plain words. A gap is retracted once its answer is recorded.

## Then

- `get_change_set(id)`: `applied`, or read the validation report and fix it.
- Tell the person what you recorded, citing claim ids with their belief, and what you could not place.
- When no gap is left, run `python3 -m design_blueprint propose <name>`: it renders the compose file and puts a
  plan in the review lane whose label is the file's whole text. Tell the person to read and approve it there;
  the intent actuator writes the file only once they have, and only if the system as described still renders
  to that text. If it refuses, tell the person why (an open question, or two values for one setting to settle).
