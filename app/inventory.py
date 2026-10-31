"""Stock ledger. A customer sale decreases stock; if stock drops below
REORDER_THRESHOLD, a purchase order is placed (through workflow) and sent to WhatsApp."""
import logging

from sqlalchemy.orm import Session

from . import config, matching, workflow
from .models import CustomerOrder, Order, StockItem
from .schemas import ParsedOrder
from .states import OrderStatus

log = logging.getLogger("munimai.inventory")


class StockError(Exception):
    def __init__(self, message: str, status: int = 422):
        super().__init__(message)
        self.status = status


def find_item(db: Session, name: str) -> StockItem | None:
    items = db.query(StockItem).all()
    sid, score = matching.match_supplier(name, [(i.id, i.name, i.aliases) for i in items])
    if sid is None or score < config.MATCH_ACCEPT:
        return None
    return db.get(StockItem, sid)


def _open_reorder(db: Session, item: StockItem) -> Order | None:
    """An unfinished PO for this item, so we never place duplicates."""
    return (
        db.query(Order)
        .filter(Order.item == item.name,
                Order.status.in_([OrderStatus.PENDING_CONFIRMATION.value, OrderStatus.CONFIRMED.value]))
        .first()
    )


def place_reorder(db: Session, item: StockItem) -> dict | None:
    if not (item.supplier_id and float(item.reorder_qty) > 0 and float(item.unit_cost) > 0):
        log.warning("item=%s is low but has no supplier/reorder_qty/unit_cost, cannot reorder", item.name)
        return None
    open_order = _open_reorder(db, item)
    if open_order:
        return {"order_id": open_order.id, "status": open_order.status, "dispatch": "already_open"}

    qty = float(item.reorder_qty)
    parsed = ParsedOrder(
        intent="LOG_PURCHASE_ORDER", supplier=item.supplier.name, item=item.name, quantity=qty,
        unit=item.unit, total_amount=round(qty * float(item.unit_cost), 2),
    )
    order = workflow.create_order(
        db, transcript=f"Auto reorder: {item.name} stock {workflow.fmt_qty(item.quantity)} "
                       f"is below {workflow.fmt_qty(config.REORDER_THRESHOLD)}",
        language=None, parsed=parsed, supplier=item.supplier, score=1.0,
        stt_ms=0, parse_ms=0, did_you_mean=False,
    )
    dispatch = None
    if config.AUTO_CONFIRM_REORDER:
        workflow.confirm_order(db, order)
        dispatch = workflow.dispatch_order(db, order)
    log.info("order=%s auto reorder for %s dispatch=%s", order.id, item.name, dispatch)
    return {"order_id": order.id, "supplier": item.supplier.name, "quantity": qty,
            "total": float(order.total), "status": order.status, "dispatch": dispatch}


def record_sale(db: Session, item_name: str, quantity: float, customer: str | None = None):
    """Returns (sale, stock_item, reorder_dict_or_None)."""
    item = find_item(db, item_name)
    if item is None:
        raise StockError(f"'{item_name}' is not in stock list", 404)
    have = float(item.quantity)
    if quantity > have:
        raise StockError(f"Only {workflow.fmt_qty(have)} {item.unit or ''} of {item.name} in stock".replace("  ", " "))

    item.quantity = round(have - quantity, 2)
    sale = CustomerOrder(customer=customer, stock_item_id=item.id, item=item.name,
                         quantity=quantity, stock_after=item.quantity)
    db.add(sale)
    db.commit()  # the sale is saved even if the reorder fails below

    reorder = None
    if float(item.quantity) < config.REORDER_THRESHOLD:
        try:
            reorder = place_reorder(db, item)
        except Exception:
            log.exception("auto reorder failed for %s", item.name)
        if reorder and reorder.get("order_id"):
            sale.reorder_order_id = reorder["order_id"]
            db.commit()
    return sale, item, reorder