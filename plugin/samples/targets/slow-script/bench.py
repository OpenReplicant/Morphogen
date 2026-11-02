"""The benchmark workload: run top_words on a generated text. Part of the judge's harness.

The judge times this whole process from outside and sets MORPHOGEN_SEED to a
fresh random value, so the input cannot be predicted. Anything printed here
is recorded as "reported" and never decides a verdict.
"""

import json
import os
import time

from gen import text
from topwords import top_words

WORDS = 15000


def main():
    seed = int(os.environ.get("MORPHOGEN_SEED", "0"))
    sample = text(seed, WORDS)
    t0 = time.perf_counter()
    top_words(sample, 20)
    print(json.dumps({"seconds": round(time.perf_counter() - t0, 6)}))


if __name__ == "__main__":
    main()
