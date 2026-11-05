"""Normalising names into tokens, and telling model codes apart from words."""

import re
import unicodedata
from difflib import SequenceMatcher

from . import settings

_SPLIT = re.compile(r"[^0-9a-z]+")
_HAS_DIGIT = re.compile(r"\d")


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def tokens(record: dict) -> list[str]:
    """Words from the name (and manufacturer, if given), with aliases expanded. Hyphenated codes are
    joined as well as split, so "PS-LX350H" yields "ps", "lx350h" and "pslx350h"."""
    text = fold(" ".join(str(record.get(k) or "") for k in ("name", "manufacturer")))
    out = []
    for chunk in text.split():
        parts = [p for p in _SPLIT.split(chunk) if p]
        out.extend(parts)
        if len(parts) > 1 and any(_HAS_DIGIT.search(p) for p in parts):
            out.append("".join(parts))
    expanded = []
    for t in out:
        expanded.extend(settings.ALIASES.get(t, t).split())
    return expanded


def model_codes(toks: list[str]) -> set[str]:
    """Tokens that look like model codes: letters and digits together, or long numbers that are not
    years."""
    codes = set()
    for t in toks:
        letters, digits = any(c.isalpha() for c in t), any(c.isdigit() for c in t)
        if letters and digits and len(t) >= 3:
            codes.add(t)
        elif digits and not letters and len(t) >= 3 and not (len(t) == 4 and t[:2] in ("19", "20")):
            codes.add(t)
    return codes


def codes_conflict(a: list[str], b: list[str]) -> bool:
    """Both names carry model codes and none of them agree."""
    ca, cb = model_codes(a), model_codes(b)
    return bool(ca and cb and not (ca & cb))


def words(toks: list[str]) -> set[str]:
    """Distinctive words: alphabetic, at least three letters, not stopwords."""
    return {t for t in toks if t.isalpha() and len(t) >= 3 and t not in settings.STOPWORDS}


def _same_word(w: str, others: set[str]) -> bool:
    if w in others:
        return True
    for o in others:
        # the ratio is at most 2*min/(len sum): skip pairs that cannot reach the bar (same result, faster)
        if 2 * min(len(w), len(o)) / (len(w) + len(o)) < settings.TYPO_RATIO:
            continue
        if SequenceMatcher(None, w, o).ratio() >= settings.TYPO_RATIO:
            return True
    return False


def words_conflict(a: list[str], b: list[str]) -> bool:
    """Each name has a distinctive word the other lacks (typos tolerated): two editions or variants
    of one line, rather than one name being a longer form of the other."""
    wa, wb = words(a), words(b)
    only_a = {w for w in wa if not _same_word(w, wb)}
    only_b = {w for w in wb if not _same_word(w, wa)}
    return bool(only_a and only_b)
