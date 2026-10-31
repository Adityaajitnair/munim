"""Fuzzy supplier matching. STT often mangles names, so match against
canonical names and aliases (including Devanagari spellings)."""
import re
import unicodedata
from difflib import SequenceMatcher

_DROP = re.compile(r"[^\w\u0900-\u097F]+")


def normalize(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    return _DROP.sub("", s)


def _score(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # one name contained in the other ("amul" vs "amuldairy")
    if min(len(a), len(b)) >= 3 and (a in b or b in a):
        return 0.9
    return SequenceMatcher(None, a, b).ratio()


def match_supplier(name, suppliers):
    """suppliers: iterable of (id, name, aliases). Returns (id or None, score)."""
    q = normalize(name)
    best_id, best = None, 0.0
    for sid, sname, aliases in suppliers:
        for cand in [sname, *(aliases or [])]:
            s = _score(q, normalize(cand))
            if s > best:
                best_id, best = sid, s
    return best_id, round(best, 3)
