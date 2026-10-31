"""Order state machine. Pure Python so it is easy to test."""
from enum import Enum


class OrderStatus(str, Enum):
    PENDING_CONFIRMATION = "PENDING_CONFIRMATION"
    CONFIRMED = "CONFIRMED"
    EXECUTED = "EXECUTED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


ALLOWED = {
    OrderStatus.PENDING_CONFIRMATION: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED},
    OrderStatus.CONFIRMED: {OrderStatus.EXECUTED, OrderStatus.FAILED},
    OrderStatus.EXECUTED: set(),
    OrderStatus.FAILED: set(),
    OrderStatus.CANCELLED: set(),
}


class IllegalTransition(Exception):
    pass


def can_transition(old: OrderStatus, new: OrderStatus) -> bool:
    return new in ALLOWED[old]


def check_transition(old: OrderStatus, new: OrderStatus) -> None:
    if not can_transition(old, new):
        raise IllegalTransition(f"Cannot move order from {old.value} to {new.value}")
