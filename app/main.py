"""MunimAI FastAPI core. Run:  uvicorn app.main:app --reload"""
import hmac
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from . import config, intent, matching, mock_whatsapp, parser, stock, stt, tts, workflow
from .db import Base, SessionLocal, engine, get_db
from .models import LedgerEntry, Order, Supplier
from .schemas import ExecutedCallback, TTSRequest
from .states import IllegalTransition, OrderStatus
from .stt import Transcript

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("munimai")

FRONTEND = Path(__file__).resolve().parent.parent / "frontend" / "index.html"

SEED_SUPPLIERS = [
    ("Amul", ["अमूल", "amool", "amul dairy"]),
    ("Mother Dairy", ["मदर डेयरी", "mother dairi"]),
    ("Parle", ["पारले", "parle g", "parley"]),
    ("Britannia", ["ब्रिटानिया", "britania"]),
    ("Haldiram", ["हल्दीराम", "haldiram's"]),
]
DEMO_WHATSAPP = "+910000000000"  # replace with your sandbox-joined number

# Starting stock, added when the ledger is empty: supplier, item, unit, quantity, amount (Rs)
SEED_LEDGER = [
    ("Britannia", "Biscuit", None, 30, 2000),
    ("Amul", "milk", "liter", 75, 2700),
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        have = {s.name for s in db.query(Supplier).all()}
        for name, aliases in SEED_SUPPLIERS:
            if name not in have:
                db.add(Supplier(name=name, aliases=aliases, whatsapp_number=DEMO_WHATSAPP))
        db.commit()

        if db.query(LedgerEntry).count() == 0:
            sup = {s.name: s.id for s in db.query(Supplier).all()}
            for sname, item, unit, qty, amount in SEED_LEDGER:
                db.add(LedgerEntry(supplier_id=sup[sname], item=item, unit=unit,
                                   quantity=qty, unit_cost=amount / qty))
            db.commit()
    yield


app = FastAPI(title="MunimAI", version="0.1", lifespan=lifespan)
app.include_router(mock_whatsapp.router)


@app.exception_handler(IllegalTransition)
async def _illegal(_, exc: IllegalTransition):
    return JSONResponse(status_code=409, content={"detail": str(exc)})


# ---------- helpers ----------

def order_dict(o: Order) -> dict:
    return {
        "order_id": o.id,
        "kind": o.kind,
        "status": o.status,
        "transcript": o.transcript,
        "language": o.language,
        "supplier": o.supplier.name if o.supplier else None,
        "item": o.item,
        "quantity": float(o.quantity),
        "unit": o.unit,
        "total": float(o.total),
        "match_confidence": o.match_confidence,
        "readback_text": o.readback_text,
        "whatsapp_message": o.whatsapp_message,
        "whatsapp_message_id": o.whatsapp_message_id,
        "error": o.error,
        "latency_ms": {"stt": o.stt_latency_ms, "parse": o.parse_latency_ms},
        "created_at": o.created_at.isoformat() if o.created_at else None,
        "executed_at": o.executed_at.isoformat() if o.executed_at else None,
    }


def get_order_or_404(db: Session, order_id: str) -> Order:
    o = db.get(Order, order_id)
    if not o:
        raise HTTPException(404, "Order not found")
    return o


async def transcript_from(audio: UploadFile | None, text: str | None) -> Transcript:
    """Text wins (UI fallback / testing); otherwise run STT on the upload."""
    if text and text.strip():
        return Transcript(text=text.strip(), language=None, latency_ms=0)
    if audio is None:
        raise HTTPException(422, {"message": "Send an audio file or text."})
    data = await audio.read()
    if not data:
        raise HTTPException(422, {"message": "Audio is empty. Please record again."})
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, {"message": "Audio file is too large."})
    try:
        return stt.transcribe(data, audio.filename or "audio.webm", audio.content_type or "audio/webm")
    except stt.STTError as e:
        log.error("STT failed: %s", e)
        raise HTTPException(502, {"message": "Speech service unavailable. Try again or type the order.", "error": str(e)})


def interpret_reply(text: str, order: Order):
    """Merchant's spoken reply -> (action, changes). action: confirm | reject | modify.
    Short bare replies ("haan", "nahi") skip the LLM; anything longer is parsed by Sarvam."""
    unclear = HTTPException(422, {"message": "Didn't catch that. Say haan to confirm, nahi to cancel, or what to change.",
                                  "transcript": text})
    if len(text.split()) <= 3:
        quick = intent.classify_reply(text)
        if quick:
            return quick, {}
    ctx = {"supplier": order.supplier.name if order.supplier else None, "item": order.item,
           "quantity": float(order.quantity), "unit": order.unit, "total": float(order.total)}
    try:
        r = parser.parse_reply(text, ctx)
    except (parser.LLMError, parser.ParseError) as e:
        log.warning("reply parse failed (%s), falling back to keywords", e)
        quick = intent.classify_reply(text)
        if quick:
            return quick, {}
        raise unclear
    log.info("order=%s reply decision=%s changes=%s", order.id, r.decision, r.changes())
    # never send an order if the words clearly include a rejection
    if r.decision == "CONFIRM":
        return ("reject", {}) if intent.classify_reply(text) == "reject" else ("confirm", {})
    if r.decision == "REJECT":
        return "reject", {}
    if r.decision == "MODIFY" and r.changes():
        return "modify", r.changes()
    raise unclear


# ---------- routes ----------

@app.get("/", include_in_schema=False)
def index():
    if FRONTEND.exists():
        return FileResponse(FRONTEND)
    return {"service": "munimai", "docs": "/docs"}


@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(sql_text("SELECT 1"))
    return {"status": "ok"}


@app.post("/voice")
async def voice(audio: UploadFile | None = File(None), text: str | None = Form(None),
                db: Session = Depends(get_db)):
    t0 = time.perf_counter()
    tr = await transcript_from(audio, text)

    t1 = time.perf_counter()
    try:
        parsed = parser.parse_order(tr.text)
    except parser.LLMError as e:
        log.error("LLM failed: %s", e)
        raise HTTPException(502, {"message": "Parser unavailable. Try again.", "transcript": tr.text, "error": str(e)})
    except parser.ParseError as e:
        raise HTTPException(422, {"message": "Didn't catch that, please repeat.", "transcript": tr.text, "error": str(e)})
    parse_ms = int((time.perf_counter() - t1) * 1000)

    log.info("transcript=%r parsed=%s", tr.text, parsed)
    if not parsed.is_complete_order():
        raise HTTPException(422, {"message": "Didn't catch that, please repeat. Say supplier, item, quantity and amount.",
                                  "transcript": tr.text})

    suppliers = [(s.id, s.name, s.aliases) for s in db.query(Supplier).all()]
    sid, score = matching.match_supplier(parsed.supplier, suppliers)
    if sid is None or score < config.MATCH_REJECT:
        raise HTTPException(422, {"message": f"Supplier '{parsed.supplier}' not recognised. Please repeat the supplier name.",
                                  "transcript": tr.text})
    supplier = db.get(Supplier, sid)

    order = workflow.create_order(
        db, transcript=tr.text, language=tr.language, parsed=parsed, supplier=supplier,
        score=score, stt_ms=tr.latency_ms, parse_ms=parse_ms,
        did_you_mean=score < config.MATCH_ACCEPT,
    )
    body = order_dict(order)
    body["latency_ms"]["total"] = int((time.perf_counter() - t0) * 1000)
    log.info("order=%s created supplier=%s score=%.2f total_ms=%d", order.id, supplier.name, score, body["latency_ms"]["total"])
    return body


@app.post("/confirm")
async def confirm(order_id: str = Form(...), decision: str | None = Form(None),
                  audio: UploadFile | None = File(None), text: str | None = Form(None),
                  db: Session = Depends(get_db)):
    """Resolve a pending order. Either an explicit decision (confirm/reject), or the merchant's
    spoken/typed reply, which Sarvam interprets: confirm, reject, or a correction.
    Confirming a customer order updates the stock ledger (and may send a restock PO to WhatsApp)."""
    order = get_order_or_404(db, order_id)
    heard, changes = None, {}

    if decision in ("confirm", "reject"):
        action = decision
    else:
        tr = await transcript_from(audio, text)
        heard = tr.text
        log.info("order=%s reply transcript=%r", order.id, heard)
        action, changes = interpret_reply(heard, order)

    if action == "reject":
        workflow.cancel_order(db, order)
        return {"order_id": order.id, "status": order.status, "action": "reject", "transcript": heard}

    if action == "modify":
        supplier, score, dym = None, None, False
        if "supplier" in changes:
            suppliers = [(s.id, s.name, s.aliases) for s in db.query(Supplier).all()]
            sid, score = matching.match_supplier(changes["supplier"], suppliers)
            if sid is None or score < config.MATCH_REJECT:
                raise HTTPException(422, {"message": f"Supplier '{changes['supplier']}' not recognised. Say the supplier name again.",
                                          "transcript": heard})
            supplier, dym = db.get(Supplier, sid), score < config.MATCH_ACCEPT
        workflow.update_order(db, order, supplier=supplier, score=score, did_you_mean=dym,
                              item=changes.get("item"), quantity=changes.get("quantity"),
                              unit=changes.get("unit"), total=changes.get("total_amount"))
        return {"order_id": order.id, "status": order.status, "action": "modify",
                "transcript": heard, "order": order_dict(order)}

    try:
        if order.status == OrderStatus.PENDING_CONFIRMATION.value and order.kind == "CUSTOMER":
            stock.check_fulfillable(db, order)  # refuse before confirming if the ledger can't fill it
        moved = workflow.confirm_order(db, order)
    except stock.LedgerError as e:
        raise HTTPException(409, {"message": str(e), "transcript": heard})
    except workflow.NotConfirmable as e:
        raise HTTPException(422, {"message": str(e)})

    result = None
    if moved and order.kind == "CUSTOMER":
        result = await run_in_threadpool(stock.apply_customer_order, db, order)  # may POST the restock webhook
    restock = result["restock"] if result else None
    return {"order_id": order.id, "status": order.status, "action": "confirm", "transcript": heard,
            "ledger": result, "restock": restock,
            "whatsapp_message": restock.get("whatsapp_message") if restock else None}


@app.post("/orders/{order_id}/executed")
def executed(order_id: str, body: ExecutedCallback, x_webhook_secret: str | None = Header(None),
             db: Session = Depends(get_db)):
    if not x_webhook_secret or not hmac.compare_digest(x_webhook_secret, config.N8N_CALLBACK_SECRET):
        raise HTTPException(401, "Bad webhook secret")
    order = get_order_or_404(db, order_id)
    workflow.mark_executed(db, order, body.success, body.message_id, body.error)
    return {"order_id": order.id, "status": order.status}


@app.post("/orders/{order_id}/retry")
def retry(order_id: str, db: Session = Depends(get_db)):
    order = get_order_or_404(db, order_id)
    return {"order_id": order.id, "dispatch": workflow.dispatch_order(db, order), "status": order.status}


@app.post("/orders/{order_id}/send-whatsapp")
def send_whatsapp(order_id: str, db: Session = Depends(get_db)):
    """Manually (re)send a CONFIRMED order's details to the WhatsApp webhook."""
    order = get_order_or_404(db, order_id)
    try:
        resp = workflow.send_to_webhook(db, order, config.WHATSAPP_WEBHOOK_URL)
    except workflow.WebhookError as e:
        raise HTTPException(502, {"message": "Webhook unreachable", "error": str(e)})
    return {"order_id": order.id, "status": order.status,
            "webhook_url": config.WHATSAPP_WEBHOOK_URL, "webhook_response": resp}


@app.get("/orders/{order_id}")
def get_order(order_id: str, db: Session = Depends(get_db)):
    return order_dict(get_order_or_404(db, order_id))


@app.get("/orders")
def list_orders(status: str | None = None, kind: str | None = None, limit: int = 20,
                db: Session = Depends(get_db)):
    q = db.query(Order)
    if status:
        q = q.filter(Order.status == status)
    if kind:
        q = q.filter(Order.kind == kind.upper())
    return [order_dict(o) for o in q.order_by(Order.created_at.desc()).limit(min(limit, 100)).all()]


@app.get("/ledger")
def ledger(db: Session = Depends(get_db)):
    """The stock ledger: one row per supplier + item."""
    rows = db.query(LedgerEntry).order_by(LedgerEntry.id).all()
    totals: dict[str, float] = {}
    entries = []
    for r in rows:
        totals[r.supplier.name] = round(totals.get(r.supplier.name, 0) + r.amount, 2)
        entries.append({"id": r.id, "supplier": r.supplier.name, "item": r.item,
                        "quantity": round(float(r.quantity), 2), "unit": r.unit,
                        "unit_cost": round(float(r.unit_cost), 2), "amount": r.amount,
                        "low": float(r.quantity) < config.REORDER_THRESHOLD})
    return {"entries": entries, "totals_by_supplier": totals, "grand_total": round(sum(totals.values()), 2),
            "reorder_threshold": config.REORDER_THRESHOLD, "restock_qty": config.RESTOCK_QTY}


@app.post("/tts")
def text_to_speech(req: TTSRequest):
    try:
        audio = tts.synthesize(req.text, req.language)
    except tts.TTSError as e:
        raise HTTPException(503, {"message": "TTS unavailable", "error": str(e)})
    return Response(content=audio, media_type="audio/wav")