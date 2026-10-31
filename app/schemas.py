from pydantic import BaseModel, field_validator

class CustomerOrderRequest(BaseModel):
    item: str
    quantity: float
    customer: str | None = None


class StockUpsert(BaseModel):
    item: str
    quantity: float
    unit: str | None = None
    supplier: str | None = None
    reorder_qty: float | None = None
    unit_cost: float | None = None

class ParsedOrder(BaseModel):
    """Strict shape the LLM must return (matches the prompt in parser.py)."""
    intent: str
    supplier: str | None = None
    item: str | None = None
    quantity: float | None = None
    unit: str | None = None
    total_amount: float | None = None

    @field_validator("intent")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    def is_complete_order(self) -> bool:
        return (
            self.intent == "LOG_PURCHASE_ORDER"
            and bool(self.supplier)
            and self.quantity is not None and self.quantity > 0
            and self.total_amount is not None and self.total_amount > 0
        )


class ParsedReply(BaseModel):
    """What the merchant meant when replying to the read-back."""
    decision: str  # CONFIRM, REJECT, MODIFY or UNCLEAR
    supplier: str | None = None
    item: str | None = None
    quantity: float | None = None
    unit: str | None = None
    total_amount: float | None = None

    @field_validator("decision")
    @classmethod
    def _upper(cls, v: str) -> str:
        return v.strip().upper()

    def changes(self) -> dict:
        """Only the fields the merchant asked to change (positive numbers, non-empty text)."""
        out = {}
        for k in ("supplier", "item", "unit"):
            v = getattr(self, k)
            if v and str(v).strip():
                out[k] = str(v).strip()
        for k in ("quantity", "total_amount"):
            v = getattr(self, k)
            if v is not None and v > 0:
                out[k] = v
        return out


class ExecutedCallback(BaseModel):
    success: bool
    message_id: str | None = None
    error: str | None = None


class TTSRequest(BaseModel):
    text: str
    language: str = "hi-IN"
