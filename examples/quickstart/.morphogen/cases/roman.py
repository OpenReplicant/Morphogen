# The case generator: the base's code. Fresh randomness on every renewal; the answers come from here.
def _roman(n):
    out = ""
    for value, letters in ((1000, "M"), (900, "CM"), (500, "D"), (400, "CD"), (100, "C"), (90, "XC"),
                           (50, "L"), (40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")):
        while n >= value:
            out += letters
            n -= value
    return out


def generate(rng, n):
    return [{"id": f"r{i:03d}", "input": {"n": k}, "answer": _roman(k)}
            for i, k in enumerate(rng.sample(range(1, 4000), n))]
