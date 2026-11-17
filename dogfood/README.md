# Dogfood: the rebuild-8 judge on Morphogen's own pull requests

`topwords/` is a toy with a known bug (it counts words case-sensitively). A pull request that changes
it, with a `morphogen-card` block in its description, is judged by `.github/workflows/morphogen.yml`:
the rebuild-8 judge, pinned by commit, scoring against held-out cases in a private repository.
The verdict appears as the `morphogen/verdict` status, with a signed verdict attached to the run.

Example card:

```morphogen-card
{"card": "morphogen.card/v1",
 "intent": "Count words case-insensitively so top_words matches the reference on mixed-case text.",
 "scope": ["dogfood/topwords/core.py"],
 "cases": {"set": "topwords-heldout"},
 "kpis": [{"name": "accuracy", "source": "scorer", "direction": "higher", "floor": 0.0, "role": "decide"},
          {"name": "wall_seconds", "source": "runner", "direction": "lower", "floor": 0.5, "role": "bound"}]}
```
