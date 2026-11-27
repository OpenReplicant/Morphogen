"""Label each number "high" or "low". THRESHOLD is the setting to tune."""
THRESHOLD = 10


def label(x):
    return "high" if x >= THRESHOLD else "low"
LIMIT = 100
