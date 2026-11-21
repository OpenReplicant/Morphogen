def to_roman(n):
    """n as a Roman numeral (1 to 3999)."""
    out = ""
    for value, letter in ((1000, "M"), (500, "D"), (100, "C"), (50, "L"), (10, "X"), (5, "V"), (1, "I")):
        while n >= value:
            out += letter
            n -= value
    return out
