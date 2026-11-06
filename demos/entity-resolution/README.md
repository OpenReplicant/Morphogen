# Entity resolution: status

Plan and build are done for a baseline; optimizing waits for Morphogen's base. See
[BRIEF.md](BRIEF.md) for the design.

| Step | State |
|---|---|
| Plan: interface tests | `tests/test_interface.py` (the resolver), `tests/test_contracts.py` (candidates, pair-score, similarity) |
| Build: two backends | `overlap` (overlap coefficient) and `tfidf` (TF-IDF cosine); both pass the interface test |
| Cells | `catalog-info.yaml` (the structure) and `morphogen.yaml` (what may change, how each is judged): backend, blocking, matcher on F1; `speed` (er/text.py) on wall time with the same output |
| Measure | `bench.py` prints the pairs it finds; `score.py`, from the base, computes F1 against answers outside the repository |
| Judged | `speed`: passed, 69% faster (below) |
| Optimize | next: tune `matcher` and `blocking` on F1 |

Run it (Python 3.11 or later, standard library only):

    python -m unittest discover -s tests -t .
    python data/fetch.py
    python data/split.py ~/er-split          # records and answers outside the repository
    MORPHOGEN_INPUTS=~/er-split/inputs python bench.py | MORPHOGEN_PRIVATE=~/er-split/search python score.py

To judge it, the demo must be the root of its own git repository (the judge reads `morphogen.yaml`
at the root), with the lines `data/split.py` prints in `morphogen.local.yaml`.

## First verdicts (2026-11-06, Abt-Buy, in Podman)

Baseline through the judge: held-out F1 0.422 (precision 0.615, recall 0.321), 37 s a run. 85% of
the time was `difflib` in `er/text.py`, comparing words for typos.

| Candidate for `speed` | Verdict | Wall time | Peak memory |
|---|---|---|---|
| check difflib's cheap upper bounds first, and cache every word pair | **fail** | 76% faster (37.1 s to 8.9 s) | +133% (21.6 to 50.5 MB), over the cell's 50% limit |
| the same, with the cache bounded to 4096 pairs | **pass** | 69% faster (36.8 s to 11.5 s, interval 67-69%, p = 0.008) | +2% |

Both printed exactly the base's pairs on every run (`same_output`), so F1 cannot have moved. The
first was refused on a constraint the change made worse, not on the metric it improved.

## Baseline before the judge (search split, 2026-11-05)

| Dataset | Backend | F1 | Precision | Recall | Time |
|---|---|---|---|---|---|
| Abt-Buy | overlap | 0.469 | 0.703 | 0.352 | 26 s |
| Abt-Buy | tfidf | 0.452 | 0.774 | 0.320 | 32 s |
| Amazon-Google | overlap | 0.406 | 0.322 | 0.549 | 65 s |
| Amazon-Google | tfidf | 0.467 | 0.418 | 0.530 | 70 s |

Far below published matchers (F1 about 0.96 on Abt-Buy and 0.79 on Amazon-Google, from search
results, trained on labelled pairs); that gap is the room for Morphogen. Low recall on Abt-Buy
suggests the mismatch rules are too strict for descriptive names; times are dominated by
`add()` resolving every right record.

## Known gaps

- Only Abt-Buy is split for the judge so far; Amazon-Google (the informative one) is 3x larger.
- The interface tests check behaviour on a small fixture; F1 is the only measure on the data.
