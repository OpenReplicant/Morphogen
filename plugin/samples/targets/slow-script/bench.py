"""Time top_words on a generated text. Part of the judge's harness.

The judge sets MORPHOGEN_SEED to a value only it knows, so the benchmark input
cannot be predicted from the repository. Prints one JSON line of metrics.
"""

import json
import os
import time

from gen import text
from topwords import top_words

WORDS = 12000


def main():
    seed = int(os.environ.get("MORPHOGEN_SEED", "0"))
    sample = text(seed, WORDS)
    t0 = time.perf_counter()
    top_words(sample, 20)
    print(json.dumps({"seconds": round(time.perf_counter() - t0, 6)}))


if __name__ == "__main__":
    main()
