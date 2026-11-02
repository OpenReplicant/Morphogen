"""Most frequent words in a text. Correct, and deliberately slow: improve it."""


def normalise(text):
    words = [w.strip(".,;:!?\"'()[]").lower() for w in text.split()]
    return [w for w in words if w]


def top_words(text, k):
    """The k most frequent words as (word, count), most frequent first, ties alphabetical."""
    words = normalise(text)
    unique = []
    for w in words:
        if w not in unique:
            unique.append(w)
    counts = [(w, words.count(w)) for w in unique]
    counts.sort(key=lambda pair: (-pair[1], pair[0]))
    return counts[:k]
