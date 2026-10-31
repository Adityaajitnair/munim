"""Mock WhatsApp. Receives the order webhook, shows it as a chat at /mock-whatsapp,
then calls back /orders/{id}/executed the way n8n would."""
import logging
import time
import uuid
from collections import deque
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import config

log = logging.getLogger("munimai.mockwa")
router = APIRouter(prefix="/mock-whatsapp", tags=["mock-whatsapp"])

MESSAGES: deque = deque(maxlen=100)
_state = {"fail": False}  # flip via POST /mock-whatsapp/fail?on=true to test the retry path


class WebhookPayload(BaseModel):
    order_id: str
    supplier: str
    whatsapp_number: str = ""
    item: str | None = None
    quantity: float | None = None
    unit: str | None = None
    total: float | None = None
    message: str
    callback_url_path: str | None = None


def _callback(msg: dict, path: str, fail: bool) -> None:
    time.sleep(1)  # pretend WhatsApp takes a moment to deliver
    body = {
        "success": not fail,
        "message_id": None if fail else msg["id"],
        "error": "Mock WhatsApp failure" if fail else None,
    }
    try:
        r = requests.post(
            config.PUBLIC_BASE_URL.rstrip("/") + path,
            json=body,
            headers={"x-webhook-secret": config.N8N_CALLBACK_SECRET},
            timeout=5,
        )
        log.info("mock callback %s -> %s", path, r.status_code)
    except requests.RequestException as e:
        log.error("mock callback failed: %s", e)
    msg["status"] = "failed" if fail else "delivered"


@router.post("/webhook")
async def webhook(p: WebhookPayload, bg: BackgroundTasks):
    msg = {
        "id": f"MOCK-{uuid.uuid4().hex[:8]}",
        "order_id": p.order_id,
        "to": p.supplier,
        "number": p.whatsapp_number,
        "text": p.message,
        "status": "sent",
        "received_at": datetime.now(timezone.utc).isoformat(),
    }
    MESSAGES.append(msg)
    log.info("mock WhatsApp received order=%s for %s", p.order_id, p.supplier)
    if p.callback_url_path:
        bg.add_task(_callback, msg, p.callback_url_path, _state["fail"])
    return {"accepted": True, "message_id": msg["id"]}


@router.get("/messages")
def messages():
    return list(MESSAGES)


@router.delete("/messages")
def clear():
    MESSAGES.clear()
    return {"cleared": True}


@router.post("/fail")
def set_fail(on: bool = True):
    _state["fail"] = on
    return {"fail": on}


PAGE = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mock WhatsApp</title>
<style>
body{margin:0;font-family:system-ui,sans-serif;background:#e5ddd5;height:100vh;display:flex;flex-direction:column}
header{background:#075e54;color:#fff;padding:12px 16px;font-weight:600}
header small{display:block;font-weight:400;opacity:.8}
#chat{flex:1;overflow-y:auto;padding:16px;display:flex;flex-direction:column;gap:8px}
.who{align-self:center;background:#fff8;border-radius:8px;padding:2px 10px;font-size:12px;color:#555}
.bubble{align-self:flex-end;max-width:80%;background:#dcf8c6;border-radius:8px;padding:8px 10px;
box-shadow:0 1px 1px #0003;white-space:pre-wrap;font-size:14px}
.meta{text-align:right;font-size:11px;color:#667;margin-top:4px}
.delivered{color:#34b7f1}.failed{color:#d33}
.empty{margin:auto;color:#667}
</style></head><body>
<header>Mock WhatsApp <small>simulated, no real messages are sent</small></header>
<div id="chat"><div class="empty">No messages yet</div></div>
<script>
const chat=document.getElementById('chat');
const tick={sent:'\\u2713 sent',delivered:'\\u2713\\u2713 delivered',failed:'\\u2717 failed'};
async function load(){
  try{
    const msgs=await (await fetch('/mock-whatsapp/messages')).json();
    chat.innerHTML='';
    if(!msgs.length){chat.innerHTML='<div class="empty">No messages yet</div>';return}
    let last=null;
    for(const m of msgs){
      if(m.to!==last){const w=document.createElement('div');w.className='who';
        w.textContent=m.to+' '+m.number;chat.appendChild(w);last=m.to}
      const b=document.createElement('div');b.className='bubble';
      const t=document.createElement('div');t.textContent=m.text;b.appendChild(t);
      const meta=document.createElement('div');meta.className='meta '+m.status;
      meta.textContent=new Date(m.received_at).toLocaleTimeString()+'  '+tick[m.status];
      b.appendChild(meta);chat.appendChild(b);
    }
    chat.scrollTop=chat.scrollHeight;
  }catch(e){}
}
load();setInterval(load,2000);
</script></body></html>"""


@router.get("", response_class=HTMLResponse, include_in_schema=False)
def page():
    return PAGE