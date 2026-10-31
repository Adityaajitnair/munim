"""
app/main.py - MunimAI's digital ledger server (Step 3).

What this is:
    A tiny web server with two jobs, matching the roadmap:
      POST /orders  -> receive a finished order from the LangGraph pipeline
                       and save it in the ledger, status = "pending".
      GET  /orders  -> show the whole ledger (every order + its status).

    NOTE: Paytm / Soundbox integration is SIMULATED in this prototype -
    this ledger is where a real integration would plug in later.

Status lifecycle (the roadmap's state machine - makes the
"nothing executes without confirmation" claim real):
    pending -> confirmed -> executed     (later steps will drive these moves)

Storage for now:
    A plain Python list in memory. Refreshing the server wipes it -
    intentional for the MVP. SQLite comes in a later step.

Run it:
    .\\venv\\Scripts\\uvicorn.exe app.main:app --port 8000
Then open in a browser:
    http://localhost:8000/docs   <- auto-generated test page for the API
    (the browser shows pages when you upgrade this file with HTML later)
"""

import time
import uuid
from typing import List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Data models - "what a valid order looks like"
# ---------------------------------------------------------------------------

class OrderIn(BaseModel):
    """Shape of an order coming *in* (from our LangGraph pipeline).

    Pydantic checks every field automatically: is quantity a number? is
    total_amount a number? If not, FastAPI answers 422 with a clear list of
    what was wrong - we don't have to write that validation by hand.
    """

    supplier: str = Field(..., description="Brand/company, e.g. 'amul'")
    item: str = Field(..., description="Product, e.g. 'milk packet'")
    quantity: float = Field(..., gt=0, description="How many")
    unit: str | None = Field(None, description="packet / carton / kg ...")
    total_amount: float | None = Field(None, ge=0, description="Rupees")
    # carry the safety flag through so the ledger shows when we guessed
    item_guessed: bool = Field(False, description="True if item came from the lookup table")


class OrderOut(OrderIn):
    """An order as stored in the ledger = incoming fields + extras."""

    id: str                       # short unique id, e.g. "a1b2c3"
    status: str                   # pending -> confirmed -> executed
    created_at: float             # unix time; ordering evidence for the demo


# ---------------------------------------------------------------------------
# "Database" - a list in memory for this MVP step
# ---------------------------------------------------------------------------

ledger: List[OrderOut] = []

# ---------------------------------------------------------------------------
# The app itself
# ---------------------------------------------------------------------------

app = FastAPI(
    title="MunimAI Ledger",
    description="Voice-first order ledger for kirana merchants (hackathon MVP).",
    version="0.1.0",
)


@app.get("/")
def home() -> dict:
    """Tiny health-check page so we can see the server is alive."""
    return {"app": "MunimAI", "orders_in_ledger": len(ledger)}


@app.post("/orders", response_model=OrderOut, status_code=201)
def add_order(order: OrderIn) -> OrderOut:
    """
    Add one order to the ledger (called by the LangGraph pipeline).

    201 = "created" in HTTP-speak. The saved order is returned with its
    id and status so the caller can refer to it later (e.g. for confirm).
    """
    saved = OrderOut(
        **order.model_dump(),
        id=uuid.uuid4().hex[:6],
        status="pending",          # nothing is executed before confirmation!
        created_at=time.time(),
    )
    ledger.append(saved)
    return saved


@app.get("/orders", response_model=List[OrderOut])
def list_orders() -> List[OrderOut]:
    """The whole ledger, oldest first."""
    return ledger


@app.get("/orders/{order_id}", response_model=OrderOut)
def get_order(order_id: str) -> OrderOut:
    """Look up one order by id (404 with a clear message if unknown)."""
    for o in ledger:
        if o.id == order_id:
            return o
    raise HTTPException(status_code=404, detail=f"No order with id '{order_id}'")
