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

import json
import time
import uuid
from pathlib import Path
from typing import List

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
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


# ---------------------------------------------------------------------------
# Metrics endpoint - benchmark results saved by test_sentences.py
# ---------------------------------------------------------------------------

RESULTS_FILE = Path("bench/results.json")


@app.get("/metrics")
def get_metrics() -> dict:
    """
    Benchmark results from the last test_sentences.py run (file bench/results.json).

    404 if the suite hasn't run yet - the dashboard shows a friendly hint.
    """
    if not RESULTS_FILE.exists():
        raise HTTPException(
            status_code=404,
            detail="No benchmark results yet. Run:  .\\venv\\Scripts\\python.exe test_sentences.py",
        )
    return json.loads(RESULTS_FILE.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Dashboard - a live HTML page at /dashboard
# ---------------------------------------------------------------------------

# Why inline HTML (and not a framework like React)?
#   Zero extra dependencies, single file, easy to explain in a hackathon.
# The page uses plain JavaScript fetch() to pull /orders and /metrics,
# and refreshes itself every few seconds - a real live dashboard.
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>MunimAI - Merchant Dashboard</title>
<style>
  body      { font-family: 'Segoe UI', sans-serif; margin: 0; background: #f4f6f8; }
  header    { background: #0b5cab; color: white; padding: 14px 24px; display: flex;
              justify-content: space-between; align-items: center; }
  header h1 { margin: 0; font-size: 20px; }
  .sim      { background: #ffc107; color: #333; border-radius: 6px; padding: 4px 10px;
              font-size: 12px; font-weight: bold; }
  main      { padding: 24px; max-width: 1000px; margin: auto; }
  .cards    { display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 24px; }
  .card     { background: white; border-radius: 10px; padding: 16px 20px; flex: 1;
              min-width: 150px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  .card .n  { font-size: 28px; font-weight: 700; color: #0b5cab; }
  .card .t  { font-size: 12px; color: #666; margin-top: 4px; }
  section   { background: white; border-radius: 10px; padding: 16px 20px; margin-bottom: 24px;
              box-shadow: 0 1px 4px rgba(0,0,0,.08); }
  h2        { margin: 0 0 10px; font-size: 16px; color: #333; }
  table     { width: 100%; border-collapse: collapse; font-size: 14px; }
  th        { text-align: left; color: #888; font-weight: 600; padding: 6px 8px;
              border-bottom: 2px solid #eee; }
  td        { padding: 6px 8px; border-bottom: 1px solid #f0f0f0; }
  .pill     { border-radius: 999px; padding: 2px 10px; font-size: 12px; font-weight: 600; }
  .pending  { background: #fff3cd; color: #856404; }
  .guessed  { background: #e2e3e5; color: #555; }
  .pass     { background: #d4edda; color: #155724; }
  .fail     { background: #f8d7da; color: #721c24; }
  .muted    { color: #888; font-style: italic; }
</style>
</head>
<body>
<header>
  <h1>📦 MunimAI - Merchant Dashboard</h1>
  <span class="sim">DEMO: Paytm / Soundbox &amp; WhatsApp are SIMULATED</span>
</header>
<main>
  <div class="cards">
    <div class="card"><div class="n" id="m-orders">-</div><div class="t">Orders in ledger</div></div>
    <div class="card"><div class="n" id="m-value">-</div><div class="t">Total value (&#8377;)</div></div>
    <div class="card"><div class="n" id="m-pending">-</div><div class="t">Pending confirmation</div></div>
    <div class="card"><div class="n" id="m-guesses">-</div><div class="t">Smart item guesses</div></div>
    <div class="card"><div class="n" id="m-bench">-</div><div class="t">Safety tests passing</div></div>
    <div class="card"><div class="n" id="m-lat">-</div><div class="t">Avg pipeline latency</div></div>
  </div>

  <section>
    <h2>🧪 Pipeline safety benchmark</h2>
    <div id="bench"><span class="muted">No benchmark data yet - run test_sentences.py</span></div>
  </section>

  <section>
    <h2>📒 Live ledger <small class="muted">(auto-refreshes)</small></h2>
    <table>
      <thead><tr><th>ID</th><th>Status</th><th>Supplier</th><th>Item</th>
                 <th>Qty</th><th>Total</th><th>Safety</th></tr></thead>
      <tbody id="ledger"><tr><td colspan="7" class="muted">loading...</td></tr></tbody>
    </table>
  </section>
</main>
<script>
const fmtRs = n => n == null ? '-' : '₹' + Number(n).toLocaleString('en-IN');

async function refresh() {
  try {
    // ---- ledger ----
    const orders = await (await fetch('/orders')).json();
    document.getElementById('m-orders').textContent = orders.length;
    document.getElementById('m-value').textContent =
      fmtRs(orders.reduce((s, o) => s + (o.total_amount || 0), 0));
    document.getElementById('m-pending').textContent =
      orders.filter(o => o.status === 'pending').length;
    document.getElementById('m-guesses').textContent =
      orders.filter(o => o.item_guessed).length;

    document.getElementById('ledger').innerHTML = orders.map(o => `
      <tr><td>${o.id}</td>
          <td><span class="pill pending">${o.status}</span></td>
          <td>${o.supplier || '-'}</td>
          <td>${o.item || '-'} ${o.item_guessed ? '<span class="pill guessed">guessed</span>' : ''}</td>
          <td>${o.quantity ?? '-'} ${o.unit || ''}</td>
          <td>${fmtRs(o.total_amount)}</td>
          <td>${o.item_guessed ? 'auto-filled' : 'spoken'}</td></tr>`).join('')
      || '<tr><td colspan="7" class="muted">No orders yet - speak or POST one!</td></tr>';

    // ---- benchmark ----
    try {
      const m = await (await fetch('/metrics')).json();
      document.getElementById('m-bench').textContent =
        `${m.summary.passed}/${m.summary.cases}`;
      document.getElementById('m-lat').textContent =
        m.summary.avg_latency.toFixed(1) + 's';
      document.getElementById('bench').innerHTML = m.cases.map(c => `
        <div style="margin:4px 0">
          <span class="pill ${c.ok ? 'pass' : 'fail'}">${c.ok ? 'PASS' : 'FAIL'}</span>
          <b>${c.file}</b> <span class="muted">(${c.secs.toFixed(1)}s)</span><br>
          <span class="muted">heard: ${c.transcript || '-'}</span><br>
          verdict: ${c.verdict}
        </div>`).join('');
    } catch {
      document.getElementById('m-bench').textContent = 'n/a';
      document.getElementById('m-lat').textContent = 'n/a';
    }
  } catch {
    document.getElementById('ledger').innerHTML =
      '<tr><td colspan="7" class="muted">Server unreachable - is uvicorn running?</td></tr>';
  }
}

refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>"""


@app.get("/dashboard", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    """The live merchant dashboard (ledger + benchmark metrics)."""
    return HTMLResponse(DASHBOARD_HTML)
