"""Print a test input: 'k' on the first line, then generated text. Part of the judge's harness.

    python gen.py SEED WORDS
"""

import random
import sys

SYLLABLES = ["ka", "lo", "mi", "ren", "sa", "tu", "vel", "or", "en", "qui", "za", "pho", "dra", "ix"]
PUNCT = ["", "", "", "", ",", ".", ";", "!", "?"]


def vocabulary(rng, size):
    words = set()
    while len(words) < size:
        words.add("".join(rng.choice(SYLLABLES) for _ in range(rng.randint(1, 3))))
    return sorted(words)


def text(seed, n_words):
    rng = random.Random(seed)
    vocab = vocabulary(rng, max(50, n_words // 8))
    weights = [1 / (i + 1) for i in range(len(vocab))]  # Zipf-like
    rng.shuffle(vocab)
    out = []
    for w in rng.choices(vocab, weights=weights, k=n_words):
        if rng.random() < 0.1:
            w = w.capitalize()
        out.append(w + rng.choice(PUNCT))
    return " ".join(out)


def main():
    seed, n = int(sys.argv[1]), int(sys.argv[2])
    k = random.Random(seed).randint(5, 25)
    print(k)
    print(text(seed, n))


if __name__ == "__main__":
    main()
