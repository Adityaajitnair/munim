"""Rule-based confirm/reject detection for the merchant's spoken reply.
Fast, free and predictable. Reject wins over confirm, so we never send an
order when the reply is ambiguous."""
import re

_TOKEN = re.compile(r"[\w\u0900-\u097F]+")

CONFIRM = [
    "haan", "han", "haa", "ha", "yes", "yeah", "ok", "okay", "confirm", "sahi",
    "theek hai", "thik hai", "kar do", "bhej do", "ji", "ji haan",
    "हाँ", "हां", "हा", "जी", "जी हाँ", "ठीक है", "कर दो", "भेज दो", "सही",
]
REJECT = [
    "nahi", "nahin", "na", "no", "cancel", "mat", "ruko", "galat", "stop",
    "नहीं", "नही", "ना", "मत", "रुको", "कैंसिल", "रद्द", "गलत",
]


def _has(norm: str, words) -> bool:
    padded = f" {norm} "
    return any(f" {w} " in padded for w in words)


def classify_reply(text: str):
    """Returns 'confirm', 'reject' or None (unclear)."""
    norm = " ".join(_TOKEN.findall((text or "").lower()))
    if _has(norm, REJECT):
        return "reject"
    if _has(norm, CONFIRM):
        return "confirm"
    return None
