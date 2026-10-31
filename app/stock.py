"""Stock ledger rules. When a customer order is confirmed, for that supplier + item:

  stock x >= REORDER_THRESHOLD (15) :  x becomes  x - ordered
  stock x <  REORDER_THRESHOLD (15) :  RESTOCK_QTY (50) is added and a restock PO is sent to the
                                       WhatsApp webhook; x becomes  x + 50 - ordered
"""
import logging

from sqlalchemy.orm import Session

from . import config, matching, workflow
from .models import LedgerEntry, Order
from .schemas import ParsedOrder

log = logging.getLogger("munimai.stock")

NO_ITEM = (None, "", "items")  # Order.item falls back to "items" when no item was spoken


class LedgerError(Exception):
    """The ledger cannot fulfil this order (-> HTTP 409)."""


def find_row(db: Session, supplier_id: int, item: str | None) -> LedgerEntry | None:
    rows = db.query(LedgerEntry).filter(LedgerEntry.supplier_id == supplier_id).all()
    if item in NO_ITEM:  # no item spoken: fine if this supplier has exactly one ledger row
        return rows[0] if len(rows) == 1 else None
    rid, score = matching.match_supplier(item, [(r.id, r.item, []) for r in rows])
    if rid is None or score < config.MATCH_ACCEPT:
        return None
    return next(r for r in rows if r.id == rid)


def check_fulfillable(db: Session, order: Order) -> None:
    """Call BEFORE confirming, so an order we cannot fill never leaves PENDING_CONFIRMATION."""
    row = find_row(db, order.supplier_id, order.item)
    if row is None and order.item in NO_ITEM:
        raise LedgerError("Which item? Please say the item name.")
    x = float(row.quantity) if row else 0.0
    available = x + config.RESTOCK_QTY if x < config.REORDER_THRESHOLD else x
    if float(order.quantity) > available:
        raise LedgerError(f"Only {workflow.fmt_qty(available)} available"
                          f"{' of ' + row.item if row else ''}. Please order less.")


def _send_restock(db: Session, row: LedgerEntry, before: float) -> dict:
    qty = config.RESTOCK_QTY
    parsed = ParsedOrder(
        intent="LOG_PURCHASE_ORDER", supplier=row.supplier.name, item=row.item, quantity=qty,
        unit=row.unit, total_amount=round(qty * row.unit_cost, 2),
    )
    po = workflow.create_order(
        db, transcript=f"Auto restock: {row.item} stock {workflow.fmt_qty(before)} "
                       f"is below {workflow.fmt_qty(config.REORDER_THRESHOLD)}",
        language=None, parsed=parsed, supplier=row.supplier, score=1.0,
        stt_ms=0, parse_ms=0, did_you_mean=False, kind="RESTOCK",
    )
    workflow.confirm_order(db, po)
    dispatch = workflow.dispatch_order(db, po)
    log.info("order=%s restock %s x%s dispatch=%s", po.id, row.item, qty, dispatch)
    return {"order_id": po.id, "quantity": qty, "total": float(po.total), "status": po.status,
            "dispatch": dispatch, "whatsapp_message": po.whatsapp_message}


def apply_customer_order(db: Session, order: Order) -> dict:
    """Update the ledger for a CONFIRMED customer order. Blocking (posts to the webhook),
    so call it from a sync route or run_in_threadpool."""
    q = float(order.quantity)
    row = find_row(db, order.supplier_id, order.item)
    if row is None:  # item not in the ledger yet: starts at 0, so it is restocked straight away
        row = LedgerEntry(supplier_id=order.supplier_id, item=order.item, unit=order.unit,
                          quantity=0.0, unit_cost=round(float(order.total) / q, 4))
        db.add(row)
        db.flush()

    before = float(row.quantity)
    needs_restock = before < config.REORDER_THRESHOLD
    row.quantity = round(before + (config.RESTOCK_QTY if needs_restock else 0.0) - q, 2)
    db.commit()  # the ledger is saved even if the webhook fails below
    workflow.mark_executed(db, order, True)  # the customer order is done once the ledger is updated
    log.info("order=%s ledger %s: %s -> %s (restock=%s)", order.id, row.item, before, row.quantity, needs_restock)

    restock = None
    if needs_restock:
        try:
            restock = _send_restock(db, row, before)
        except Exception as e:  # ledger already updated; the PO can be retried
            log.exception("restock failed for %s", row.item)
            restock = {"error": str(e)}
    return {"supplier": order.supplier.name, "item": row.item, "unit": row.unit, "before": before,
            "ordered": q, "after": row.quantity, "restocked": config.RESTOCK_QTY if needs_restock else 0,
            "amount": row.amount, "restock": restock}