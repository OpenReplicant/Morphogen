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
| the system ("a small online shop") | `urn:kk:system:<name>` a `<KKT>ServiceTemplate`; `rdfs:label` "<name>" |
| a service ("a storefront", "a cart service", "MySQL") | `urn:kk:node:<name>:<service>` a `<KKT>NodeTemplate`; `rdfs:label`; `<KKT>memberOf` the system |
| what it runs ("the cart is registry.example.org/shop/cart:2.0.1") | `<service>` `<KKT>propertyValue` "<image>" with qualifier `<KKT>propertyName` (written out in full): `image`. Record it as said; the gap finder asks for a digest when it has none |
| a setting ("give the cart CART_TTL_HOURS of 48") | `<service>` `<KKT>propertyValue` "<value>" with qualifier `<KKT>propertyName`: the variable's name (`command` for a command) |
| who calls whom ("the storefront calls the cart", "orders go into MySQL") | `<caller>` `<KKT>connectsTo` `<callee>` |
| a limit ("the storefront should answer within 800 ms") | `<service>` `<BBO>maxValue` <number, in seconds for times> with qualifier `<SOSA>observedProperty`: `urn:kk:property:latency-seconds-mean` (no other qualifier: a qualifier more makes it a plan's prediction) |

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
{"idempotency_key": "interview:shop|urn:kk:message:shop:shop-intake:3",
 "attributed_to": "<your agent IRI>", "generated_by": "<your run id>", "target_scope": "urn:kk:scope:default",
 "ops": [
  {"op": "add_claim", "subject": "urn:kk:node:shop:cart", "predicate": "rdf:type", "object": {"entity": "kkt:NodeTemplate"},
   "evidence_type": "extracted", "references": [{"source_uri": "urn:kk:message:shop:shop-intake:3", "quote": "a cart service"}]},
  {"op": "add_claim", "subject": "urn:kk:node:shop:cart", "predicate": "kkt:propertyValue",
   "object": {"value": {"@value": "registry.example.org/shop/cart:2.0.1"}}, "qualifiers": {"https://w3id.org/knowledge-kernel/tosca#propertyName": "image"},
   "evidence_type": "extracted", "references": [{"source_uri": "urn:kk:message:shop:shop-intake:3", "quote": "registry.example.org/shop/cart:2.0.1"}]},
  {"op": "add_claim", "subject": "urn:kk:node:shop:storefront", "predicate": "https://www.irit.fr/recherches/MELODI/ontologies/BBO#maxValue",
   "object": {"value": {"@value": 0.8}}, "qualifiers": {"http://www.w3.org/ns/sosa/observedProperty": "urn:kk:property:latency-seconds-mean"},
   "evidence_type": "extracted", "references": [{"source_uri": "urn:kk:message:shop:shop-intake:3", "quote": "the storefront should answer within 800 ms"}]}]}
```

(A shop described in message 3: "... a cart service, registry.example.org/shop/cart:2.0.1 ... the storefront should answer within 800 ms ...".)

## Ask next about the gaps

The gap finder lists what the map lacks, as questions: `query_claims(predicate="oa:hasTarget")` from
`urn:kk:agent:map-gaps`, then `get_entity(<gap>)` for its kind and its question (`oa:bodyValue`). Kinds:
`unknown-peer` (a service calls something not on the map), `no-image` (what runs a service), `unpinned-image`
(the image's digest: Morphogen runs only images pinned as `name@sha256:...`, so what runs is what a person
approved), `unconnected` (how a service fits with the rest), `no-limit` (how long the service people use may
take before something should change). Ask about one or two at a time, in plain words. A gap is retracted once its
answer is recorded. When the person gives the digest of an image they named by tag, record the pinned image
(quoting them, with `"ref": "img"`) and, in the same change set, supersede your earlier image claim for that service
by it: `{"op": "set_status", "claim": "<its id>", "status": "deprecated", "reason": "superseded", "replaced_by": "img",
"expect_status": "normal"}`. Two current images for one service is a conflict, and nothing is proposed until it is
settled.

## Then

- `get_change_set(id)`: `applied`, or read the validation report and fix it.
- Tell the person what you recorded, citing claim ids with their belief, and what you could not place.
- When no gap is left, run `python3 -m design_blueprint propose <name>`: it renders the compose file and puts a
  plan in the review lane whose label is the file's whole text. Tell the person to read and approve it there;
  the intent actuator writes the file only once they have, and only if the system as described still renders
  to that text. If it refuses, tell the person why (an open question, or two values for one setting to settle).
