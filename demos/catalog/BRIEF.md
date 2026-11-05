# Catalog

Take in entities as an agent meets them: decide which known entity something is, classify it
under whatever schemes have been adopted, and attach what is known about it with its source and
trust. Cataloging is a cognitive function on its own: a model knows entities from its weights,
without identity, source, date or a way to be corrected; a catalog gives it all four.

It may be a skill plus a few scripts, on a store behind a small interface.

## Interface

```python
class Catalog(Protocol):
    def put(self, entity: dict) -> str: ...                       # id, names and aliases
    def resolve(self, mention: dict) -> list[tuple[str, float]]: ...   # via entity-resolution
    def classify(self, id: str, scheme: str, cls: str, by: str, trust: str) -> None: ...
    def claim(self, id: str, claim: dict, source: str, trust: str,
              valid_from: str | None = None, valid_to: str | None = None) -> str: ...
    def query(self, **where) -> list[dict]: ...
```

An entry: an id and aliases; classifications (scheme, class, by whom, trust); claims (source,
trust, validity period); attached models (tests, parameters, simulators).

## Trust ladder

| How it was learned | Trust |
|---|---|
| recalled from weights | hypothesis, until a lookup or observation confirms it |
| looked up in a source | stated, with provenance |
| used or observed | observed |
| tested against a model of it | measured |

A confidently recalled entity that does not exist (a hallucinated package name, for one) stays a
hypothesis and is never acted on.

## Rules

- **Several schemes at once.** The same package is a `library` in CycloneDX, a component in
  Backstage and a dependency in the code graph. Each classification names its scheme.
- **Categories earn their place.** A class stays while a query, a decision or a test uses it;
  an unused one is proposed for removal. New classes arrive as proposals, reviewed.
- **Facts are closed, not deleted.** A superseded claim gets an end date.

## Backends

| Backend | Gives | Lacks |
|---|---|---|
| graphiti | episodes as provenance, time-bounded facts, entity resolution, typed entities | trust classes, pruning; needs a graph database |
| cognee | swappable pipeline steps, OWL ontology alignment | time-bounded facts (from what was read) |
| SQLite claims table | one file, enough to start | entity resolution, scheme alignment |

Trust classes, pruning and promotion to tests live in the catalog, not the backend.

## Cells

| Cell | Parameters (owner) |
|---|---|
| `resolve` (the entity-resolution backend) | backend (agent, choices), threshold (agent, range) |
| `classify` (which scheme and class) | scheme set (operator), confidence floor (agent, range) |
| `prune` (removing unused classes) | minimum uses, window (operator) |

## Measure

- Resolution F1 on held-out mentions (from entity-resolution).
- Classification accuracy on a labelled set, per scheme.
- Hypothesis leakage: the share of recalled-only claims acted on, which must be zero.

## Done when

- The catalog runs on two backends through the same interface, and the measures tell them apart.
- A recalled-only entity is never acted on, as a red-team case.
