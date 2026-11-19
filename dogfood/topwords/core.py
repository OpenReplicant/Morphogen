from collections import Counter


def top_words(text, k):
    """The k most frequent words, most frequent first, ties alphabetical."""
    counts = Counter(text.lower().split())
    return [w for w, _ in sorted(counts.items(), key=lambda x: (-x[1], x[0]))[:k]]
