"""Pure-logic tests (no network, no DB). Run: pytest tests/test_logic.py"""
import pytest

from app.intent import classify_reply
from app.matching import match_supplier
from app.states import IllegalTransition, OrderStatus as S, can_transition, check_transition

SUPPLIERS = [(1, "Amul", ["अमूल", "amool"]), (2, "Mother Dairy", ["मदर डेयरी"]), (3, "Parle", ["पारले"])]


def test_legal_transitions():
    assert can_transition(S.PENDING_CONFIRMATION, S.CONFIRMED)
    assert can_transition(S.PENDING_CONFIRMATION, S.CANCELLED)
    assert can_transition(S.CONFIRMED, S.EXECUTED)
    assert can_transition(S.CONFIRMED, S.FAILED)


def test_illegal_transitions():
    for old, new in [(S.PENDING_CONFIRMATION, S.EXECUTED), (S.CANCELLED, S.CONFIRMED),
                     (S.EXECUTED, S.CONFIRMED), (S.FAILED, S.EXECUTED), (S.CONFIRMED, S.CANCELLED)]:
        with pytest.raises(IllegalTransition):
            check_transition(old, new)


def test_matching():
    assert match_supplier("Amul", SUPPLIERS) == (1, 1.0)
    assert match_supplier("अमूल", SUPPLIERS)[0] == 1
    assert match_supplier("Amul Dairy", SUPPLIERS)[0] == 1
    assert match_supplier("mother dairy", SUPPLIERS)[0] == 2
    assert match_supplier("Zzzzqq", SUPPLIERS)[1] < 0.5


@pytest.mark.parametrize("text,expected", [
    ("haan", "confirm"), ("Haan, bhej do.", "confirm"), ("हाँ", "confirm"), ("theek hai", "confirm"),
    ("nahi", "reject"), ("नहीं", "reject"), ("haan nahi", "reject"), ("cancel kar do", "reject"),
    ("kuch aur", None), ("", None),
])
def test_reply(text, expected):
    assert classify_reply(text) == expected
