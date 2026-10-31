"""Order lifecycle. The ONLY module that changes Order.status."""
import logging
import uuid
from datetime import datetime, timezone

import requests
from sqlalchemy.orm import Session

from . import config
from .models import LedgerEntry, Order, Supplier
from .states import IllegalTransition, OrderStatus, check_transition

log = logging.getLogger("munimai.workflow")

from . import config, matching          # add matching to the existing import
from .models import LedgerEntry, Order, StockItem, Supplier   # add StockItem

def _restock(db: Session, order: Order) -> None:
    if not order.item or order.item == "items":
        return
    qty = float(order.quantity)
    cost = round(float(order.total) / qty, 2) if qty else 0
    items = db.query(StockItem).all()
    sid, score = matching.match_supplier(order.item, [(i.id, i.name, i.aliases) for i in items])
    if sid is not None and score >= config.MATCH_ACCEPT:
        s = db.get(StockItem, sid)
        s.quantity = float(s.quantity) + qty
        s.unit_cost = cost
        s.unit = s.unit or order.unit
    else:
        db.add(StockItem(name=order.item, aliases=[], quantity=qty, unit=order.unit,
                         supplier_id=order.supplier_id, reorder_qty=qty, unit_cost=cost))

class WebhookError(Exception):
    """Webhook unreachable or returned an error status."""


def _payload(order: Order) -> dict:
    return {
        "order_id": order.id,
        "supplier": order.supplier.name,
        "whatsapp_number": order.supplier.whatsapp_number,
        "item": order.item,
        "quantity": float(order.quantity),
        "unit": order.unit,
        "total": float(order.total),
        "message": order.whatsapp_message,
        "callback_url_path": f"/orders/{order.id}/executed",
    }


def send_to_webhook(db: Session, order: Order, url: str) -> dict:
    """POST a CONFIRMED order's details to a webhook. Status stays CONFIRMED until the callback."""
    if order.status != OrderStatus.CONFIRMED.value:
        raise IllegalTransition("Only CONFIRMED orders can be sent")
    try:
        r = requests.post(url, json=_payload(order), timeout=5)
        r.raise_for_status()
        return r.json()
    except (requests.RequestException, ValueError) as e:
        order.error = f"webhook failed: {e}"
        db.commit()
        raise WebhookError(str(e)) from e

class NotConfirmable(Exception):
    """Order has no matched supplier, so it must not be sent."""


def _now():
    return datetime.now(timezone.utc)


def fmt_qty(q) -> str:
    q = float(q)
    return str(int(q)) if q == int(q) else f"{q:g}"


def fmt_inr(v) -> str:
    v = float(v)
    return f"{int(v):,}" if v == int(v) else f"{v:,.2f}"


def build_readback(supplier: str, order: Order, did_you_mean: bool = False) -> str:
    unit = f" {order.unit}" if order.unit else ""
    item = f" {order.item}" if order.item != "items" else ""
    prefix = f"Kya aapka matlab {supplier} hai? " if did_you_mean else ""
    return (
        f"{prefix}{supplier} ke {fmt_qty(order.quantity)}{unit}{item}, "
        f"total {fmt_inr(order.total)} rupaye. Confirm karein? Haan ya nahi bolein."
    )


def build_po_message(order: Order, supplier: Supplier) -> str:
    unit = f" {order.unit}" if order.unit else ""
    return (
        f"Purchase Order\nTo: {supplier.name}\n"
        f"Item: {order.item}\nQuantity: {fmt_qty(order.quantity)}{unit}\n"
        f"Amount: Rs {fmt_inr(order.total)}\nOrder ref: {order.id[:8]}"
    )


def create_order(db: Session, *, transcript: str, language, parsed, supplier: Supplier,
                 score: float, stt_ms: int, parse_ms: int, did_you_mean: bool) -> Order:
    order = Order(
        status=OrderStatus.PENDING_CONFIRMATION.value,
        transcript=transcript, language=language, supplier_id=supplier.id,
        item=parsed.item or "items", quantity=parsed.quantity, unit=parsed.unit,
        total=parsed.total_amount, match_confidence=score,
        stt_latency_ms=stt_ms, parse_latency_ms=parse_ms,
    )
    order.supplier = supplier
    order.readback_text = build_readback(supplier.name, order, did_you_mean)
    db.add(order)
    db.commit()
    return order


def update_order(db: Session, order: Order, *, supplier: Supplier | None = None, score=None,
                 did_you_mean: bool = False, item=None, quantity=None, unit=None, total=None) -> Order:
    """Apply a spoken correction. Only allowed while the order is still PENDING_CONFIRMATION;
    status does not change, the read-back is regenerated."""
    if order.status != OrderStatus.PENDING_CONFIRMATION.value:
        raise IllegalTransition(f"Cannot change an order that is {order.status}")
    if supplier is not None:
        order.supplier = supplier
        order.supplier_id = supplier.id
        order.match_confidence = score
    if item:
        order.item = item
    if quantity is not None and quantity > 0:
        order.quantity = quantity
    if unit:
        order.unit = unit
    if total is not None and total > 0:
        order.total = total
    order.readback_text = build_readback(order.supplier.name, order, did_you_mean)
    db.commit()
    return order


def _set_status(order: Order, new: OrderStatus) -> None:
    check_transition(OrderStatus(order.status), new)
    order.status = new.value


def confirm_order(db: Session, order: Order) -> bool:
    """Returns True if this call moved the order to CONFIRMED (caller should dispatch).
    Idempotent: re-confirming a CONFIRMED/EXECUTED order returns False."""
    if order.status in (OrderStatus.CONFIRMED.value, OrderStatus.EXECUTED.value):
        return False
    if order.supplier_id is None:
        raise NotConfirmable("No matched supplier")
    _set_status(order, OrderStatus.CONFIRMED)
    order.confirmed_at = _now()
    order.whatsapp_message = build_po_message(order, order.supplier)
    db.commit()
    return True


def cancel_order(db: Session, order: Order) -> None:
    if order.status == OrderStatus.CANCELLED.value:
        return
    _set_status(order, OrderStatus.CANCELLED)
    db.commit()


def mark_executed(db: Session, order: Order, success: bool, message_id=None, error=None) -> None:
    if order.status in (OrderStatus.EXECUTED.value, OrderStatus.FAILED.value):
        return  # callbacks may be retried
    if success:
        _set_status(order, OrderStatus.EXECUTED)
        order.executed_at = _now()
        order.whatsapp_message_id = message_id
        db.add(LedgerEntry(order_id=order.id, supplier_id=order.supplier_id, amount=order.total))
    else:
        _set_status(order, OrderStatus.FAILED)
        order.error = error or "WhatsApp send failed"
    db.commit()

def dispatch_order(db: Session, order: Order) -> str:
    if order.status != OrderStatus.CONFIRMED.value:
        raise IllegalTransition("Only CONFIRMED orders can be dispatched")
    url = config.N8N_WEBHOOK_URL or config.WHATSAPP_WEBHOOK_URL
    if not url:
        mark_executed(db, order, True, message_id=f"SIM-{uuid.uuid4().hex[:8]}")
        log.info("order=%s simulated WhatsApp send", order.id)
        return "simulated"
    payload = _payload(order)
    try:
        r = requests.post(url, json=payload, timeout=5)
        r.raise_for_status()
        log.info("order=%s sent to %s", order.id, url)
        return "n8n" if config.N8N_WEBHOOK_URL else "mock_whatsapp"
    except requests.RequestException as e:
        log.error("order=%s webhook failed: %s", order.id, e)
        order.error = f"webhook failed: {e}"
        db.commit()
        return "n8n_failed"
