# Demos

Projects a fresh Morphogen instance can start building, and that Morphogen can then drive. Each
is a component that stands alone, or a larger system built from them.

| Demo | What it is | Builds on |
|---|---|---|
| [entity-resolution](entity-resolution/BRIEF.md) | decide whether two records name the same entity, behind one interface with swappable backends | nothing |
| [catalog](catalog/BRIEF.md) | take in entities: resolve, classify under adopted schemes, attach claims with trust | entity-resolution |
| [cognitive-model](cognitive-model/BRIEF.md) | the Common Model of Cognition on Claude Code | catalog, and the rest of its spec |

Build them in that order: each one's points become available to the next.

## Rules

1. **A demo starts as a brief, not code.** The brief says what the system is for, its points
   (interface tests, parameters with owners), its measure and held-out cases, and its
   alternatives. A builder makes the tests pass; Morphogen improves it from there.
2. **The core never imports from `demos/`.** Demos depend on Morphogen, never the reverse.
3. **A demo graduates to its own repository** once it has working code that stands alone. Its
   folder here then keeps the brief and a link.
4. **Nothing private.** This repository is public.
