# Entity resolution: status

Plan and build are done for a baseline; optimizing waits for Morphogen's base. See
[BRIEF.md](BRIEF.md) for the design.

| Step | State |
|---|---|
| Plan: interface tests | `tests/test_interface.py`: variants, near-miss models and editions, unknowns, ordering, merge and split |
| Build: two backends | `overlap` (overlap coefficient) and `tfidf` (TF-IDF cosine); both pass the interface test |
| Cells | `cells.yaml`: backend, blocking, matcher, with parameters in `er/settings.py` |
| Measure | `bench.py`: F1 on a fixed search/holdout split of left records (70/30) |
| Optimize | not started: needs the judge, held-out scoring outside the candidate, and an optimizer adapter |

Run it (Python 3.11 or later, standard library only):

    python -m unittest discover -s tests
    python data/fetch.py
    python bench.py --dataset amazon-google --backend tfidf

## Baseline (search split, 2026-11-05)

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

- `bench.py` runs the candidate's code and computes F1 in the same process, so a candidate could
  change its own score. The judge must score predictions in a separate process, against gold
  pairs the candidate cannot read.
- The holdout split is computed in plain sight; only the judge should hold its gold pairs.
