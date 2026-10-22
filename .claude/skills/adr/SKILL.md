---
name: adr
description: Write a decision record in docs/decisions/. Use when a design choice is settled, when an existing decision is superseded, or when the user says /adr.
---
# Write a decision record

1. Next number: highest in `docs/decisions/` + 1, zero-padded to 4 digits; filename `NNNN-short-slug.md`.
2. Format:

```
# NNNN Title

Status: accepted | proposed | superseded by NNNN · YYYY-MM-DD

**Decision.** What was decided, in a few sentences.

**Why.** The reasons and alternatives rejected.

**Consequences.** What this changes or constrains.
```

3. If it supersedes a record, edit only that record's Status line to `superseded by NNNN`.
4. If it changes an invariant, vocabulary or stack line, update `CLAUDE.md` and `docs/architecture.md` in the same change.
