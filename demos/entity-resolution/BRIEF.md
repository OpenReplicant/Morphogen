# Entity resolution

Decide whether two records refer to the same entity, and group records that do. One interface,
swappable backends, so any system that needs it (a catalog, a knowledge base, a cognitive model)
can change backend without changing its code. It is also the first system for the three-arm
comparison in the [restart brief](../../BRIEF.md#value-claims-and-how-to-test-them): measurable,
with real alternatives and real parameters.

## Interface

```python
class Resolver(Protocol):
    def add(self, record: dict) -> str: ...              # returns the entity id it was assigned to
    def match(self, a: dict, b: dict) -> float: ...       # probability they are the same entity
    def resolve(self, record: dict) -> list[tuple[str, float]]: ...   # candidate entities, best first
    def merge(self, a: str, b: str) -> str: ...           # an operator or a test says they are one
    def split(self, entity: str, records: list[str]) -> str: ...      # ... or that they are not
```

The interface test any backend must pass: a fixed set of labelled pairs and groups, including
aliases, typos, abbreviations, and near-misses that must not match.

## Cells

| Cell | Modality | Parameters (owner) |
|---|---|---|
| `blocking` (which pairs are compared at all) | code, numeric | blocking key (agent, choices), window size (agent, range) |
| `matcher` (scores a pair) | code, text, model | threshold (agent, range [0.5, 0.99]), model (operator, choices) |
| `clustering` (pairs into groups) | code | method (agent, choices), linkage threshold (agent, range) |
| `backend` (the whole implementation) | alternatives | which backend (agent, choices) |

Interfaces: `blocking` provides `candidates`, `backend` provides `similarity` to `matcher`, which
provides `pair-score` to `clustering`; the root provides `resolver`. A structural change, such as replacing
blocking with embedding search, must keep the matcher's interface test green.

## Measure

- Primary: F1 on held-out labelled pairs.
- Constraints: cost per thousand records (model calls, observed from outside), wall time,
  precision floor (a wrong merge is worse than a missed one in a catalog).
- Held-out: the judge keeps a test split no optimizer or builder sees.

## Data

Public labelled benchmarks with fixed splits:

| Dataset | Domain | Entities | Matches |
|---|---|---|---|
| Abt-Buy | products | 1,081 + 1,092 | 1,097 |
| Amazon-Google | products | 1,363 + 3,226 | 1,300 |
| DBLP-ACM | bibliographic | 2,614 + 2,294 | 2,224 |

From the Leipzig database group (Creative Commons; cite the VLDB 2010 evaluation paper). The
University of Mannheim publishes fixed development and test splits; its baselines reach F1 of
about 0.85, 0.79 and 1.00 on these three. Published deep and embedding matchers report about
0.96, 0.79 and 1.00. DBLP-ACM is nearly solved, so Amazon-Google is the informative one.

## Alternatives to read before building

- graphiti's deduplication (name similarity, with model calls) and cognee's resolution: read
  their source.
- Magellan (VLDB 2016), DeepMatcher, Ditto (pre-trained language models), EAGER (embeddings for
  knowledge graphs), entity matching with large language models (arXiv 2310.11244), pyJedAI.
- Not yet read: Ditto's own paper and scores.

## Planned application: resolve-first ingestion

Knowledge-graph tools such as graphiti and cognee ingest by asking a model, per chunk, what
entities and relations it holds, then asking again whether each is already known. That is slow,
costly, not repeatable, and lets the model invent types and relations. The planned application of
this resolver is a stage that plugs into them, built for them rather than against them, where the
model handles only the margin:

1. **Extract loose mentions** (a cheap model call or rules): names, types, relations as written.
2. **Resolve deterministically, cheapest first:** exact or alias match, lexical similarity,
   embedding nearest neighbours.
3. **Only the ambiguous remainder goes to a model,** choosing among the retrieved candidates.
4. **Record every decision as an SSSOM mapping:** predicate (exact, close, broader, narrower),
   justification, confidence, tool.
5. **Confirmed decisions become aliases,** so the same mention resolves deterministically next time.
6. **New types and relations are proposals,** never silent schema changes.

What exists already (read 2026-11-05, secondary sources): Zep reports graphiti moved to a
deterministic similarity pass before any model call for deduplication, with short names still
going to the model; OntoGPT's SPIRES (Bioinformatics 2024) grounds model extractions to existing
ontologies with lexical grounders. What would be new: decisions that become deterministic as they
are learned, SSSOM records of why two mentions are one, grounding of types and relations as well
as entities outside biomedicine, and a resolver Morphogen tunes against held-out answers.

**Measure before building it:** the same corpus through graphiti as it is and through graphiti
with this stage, and the benchmark pairs above: model calls per document, time, agreement between
reruns, duplicate entities left, and linking F1 against gold. If the gap is small, it is not
worth a product.

## Done when

- Two backends pass the interface test, and the judge can tell their F1 apart on held-out pairs.
- Morphogen runs one optimizer on `matcher` and one on `blocking`, and the verdicts record the
  parameter values.
- Red team: a backend that memorises the training pairs, or reads the held-out split, is refused.
