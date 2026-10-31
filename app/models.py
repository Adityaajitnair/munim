import uuid
from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .states import OrderStatus


def _now():
    return datetime.now(timezone.utc)


class Supplier(Base):
    __tablename__ = "suppliers"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    aliases: Mapped[list] = mapped_column(JSON, default=list)
    whatsapp_number: Mapped[str] = mapped_column(String(32), default="")


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    status: Mapped[str] = mapped_column(String(32), default=OrderStatus.PENDING_CONFIRMATION.value, index=True)
    # CUSTOMER = spoken customer order (changes the ledger); RESTOCK = auto purchase order sent to WhatsApp
    kind: Mapped[str] = mapped_column(String(16), default="CUSTOMER")
    transcript: Mapped[str] = mapped_column(Text)
    language: Mapped[str | None] = mapped_column(String(16), nullable=True)
    supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"), nullable=True)
    item: Mapped[str] = mapped_column(String(200))
    quantity: Mapped[float] = mapped_column(Numeric(12, 2))
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    total: Mapped[float] = mapped_column(Numeric(12, 2))
    match_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    readback_text: Mapped[str] = mapped_column(Text, default="")
    whatsapp_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    whatsapp_message_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    stt_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    parse_latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    supplier: Mapped[Supplier | None] = relationship()


class LedgerEntry(Base):
    """Stock ledger: ONE row per supplier + item. Quantity moves with customer orders and restocks;
    amount is the value of the stock on hand (quantity x unit_cost)."""
    __tablename__ = "ledger_entries"
    __table_args__ = (UniqueConstraint("supplier_id", "item"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"))
    item: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str | None] = mapped_column(String(32), nullable=True)
    quantity: Mapped[float] = mapped_column(Float, default=0.0)
    unit_cost: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    supplier: Mapped[Supplier] = relationship()

    @property
    def amount(self) -> float:
        return round(float(self.quantity) * float(self.unit_cost), 2)