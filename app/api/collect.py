"""Collections API: payment page + webhooks, replies, demo controls, state, alerts."""
import html
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import (ActionAudit, Approval, Commitment, Customer, LedgerEntry,
                           OutboxMessage, Shop)
from app.db.session import get_db
from app.engine import clock
from app.engine.ladder import outstanding
from app.engine.payments import handle_payment
from app.engine.replies import handle_reply, resolve_approval
from app.jobs.scheduler import tick
from app.tools.ledger_tools import get_balance

router = APIRouter()
WEB = Path(__file__).resolve().parents[2] / "web"


def _shop(db) -> Shop:
    shop = db.scalars(select(Shop).order_by(Shop.id)).first()
    if shop is None:
        raise HTTPException(404, "no shop")
    return shop


class PayIn(BaseModel):
    gateway_ref: str
    amount: int
    entry_id: Optional[int] = None
    customer_id: Optional[int] = None


class ReplyIn(BaseModel):
    text: str
    customer_id: Optional[int] = None
    phone: Optional[str] = None


class AdvanceIn(BaseModel):
    days: int = 0
    hours: int = 0


@router.get("/console")
def console():
    return FileResponse(WEB / "console.html")


PAY_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Paytm (mock)</title><style>body{font-family:system-ui;background:#eaf4ff;display:flex;justify-content:center;padding:24px}
.c{background:#fff;border-radius:14px;padding:22px;max-width:380px;width:100%;box-shadow:0 2px 12px #0002}
h2{color:#002e6e;margin:0 0 4px}button{padding:10px 14px;border:0;border-radius:8px;background:#00baf2;color:#fff;font-size:16px;cursor:pointer;margin-top:10px}
button.g{background:#888}input{font-size:18px;padding:8px;width:120px}pre{background:#f4f4f4;padding:8px;border-radius:6px;font-size:12px;white-space:pre-wrap}</style></head>
<body><div class="c"><h2>Paytm <small style="color:#888">(mock page)</small></h2>
<p>Pay <b>__SHOP__</b><br>For: __CUST__ (entry #__ENTRY__)<br>Outstanding: <b>₹__AMT__</b></p>
Amount ₹ <input id="amt" type="number" value="__AMT__"><br>
<button onclick="pay(false)">Pay now (UPI)</button>
<button class="g" onclick="pay(true)">Send same webhook again (duplicate test)</button>
<pre id="out"></pre></div>
<script>let last=null;
async function pay(dup){const amt=parseInt(document.getElementById('amt').value);
if(!dup||!last){last={gateway_ref:'MOCK-'+Math.random().toString(36).slice(2,10).toUpperCase(),entry_id:__ENTRY__,amount:amt};}
const r=await fetch('/webhooks/payment',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(last)});
document.getElementById('out').textContent=JSON.stringify(await r.json(),null,2);}</script></body></html>"""


@router.get("/pay/{entry_id}", response_class=HTMLResponse)
def pay_page(entry_id: int, db: Session = Depends(get_db)):
    e = db.get(LedgerEntry, entry_id)
    if e is None or e.type != "credit":
        raise HTTPException(404, "entry not found")
    shop, cust = db.get(Shop, e.shop_id), db.get(Customer, e.customer_id)
    page = (PAY_HTML.replace("__SHOP__", html.escape(shop.name)).replace("__CUST__", html.escape(cust.name))
            .replace("__ENTRY__", str(e.id)).replace("__AMT__", str(max(outstanding(e), 0))))
    return HTMLResponse(page)


@router.post("/webhooks/payment")
def webhook_payment(body: PayIn, db: Session = Depends(get_db)):
    shop = _shop(db)
    return handle_payment(db, shop.id, body.gateway_ref, body.amount,
                          entry_id=body.entry_id, customer_id=body.customer_id)


@router.post("/webhooks/whatsapp")
def webhook_whatsapp(body: ReplyIn, db: Session = Depends(get_db)):
    shop = _shop(db)
    cid = body.customer_id
    if cid is None and body.phone:
        c = db.scalar(select(Customer).where(Customer.shop_id == shop.id, Customer.phone == body.phone))
        cid = c.id if c else None
    if cid is None:
        raise HTTPException(404, "customer not found")
    return handle_reply(db, shop.id, cid, body.text)


@router.post("/demo/advance")
def demo_advance(body: AdvanceIn):
    clock.advance(days=body.days, hours=body.hours)
    return {"now": clock.now().isoformat(), "offset_days": clock.offset_days()}


@router.post("/demo/reset_clock")
def demo_reset():
    clock.reset()
    return {"now": clock.now().isoformat(), "offset_days": 0}


@router.post("/demo/tick")
def demo_tick(db: Session = Depends(get_db)):
    return tick(db, _shop(db).id)


@router.post("/approvals/{approval_id}/resolve")
def approvals_resolve(approval_id: int, db: Session = Depends(get_db)):
    return resolve_approval(db, approval_id)


@router.get("/alerts")
def alerts(after: int = 0, db: Session = Depends(get_db)):
    shop = _shop(db)
    rows = db.scalars(select(ActionAudit).where(
        ActionAudit.shop_id == shop.id, ActionAudit.tool == "shop_alert",
        ActionAudit.id > after).order_by(ActionAudit.id)).all()
    return [{"id": a.id, "text": a.arguments.get("text", ""), "at": a.timestamp.isoformat()} for a in rows]


@router.get("/alerts/{alert_id}/audio")
def alert_audio(alert_id: int, db: Session = Depends(get_db)):
    a = db.get(ActionAudit, alert_id)
    if a is None or a.tool != "shop_alert":
        raise HTTPException(404, "not found")
    try:
        from app.voice.tts import speak
        wav = speak(a.arguments["text"], a.arguments.get("lang", "hi-IN"))
    except Exception as e:
        raise HTTPException(503, f"tts unavailable: {e}")
    return Response(wav, media_type="audio/wav")


@router.get("/state")
def state(db: Session = Depends(get_db)):
    shop = _shop(db)
    names = {c.id: c.name for c in db.scalars(select(Customer).where(Customer.shop_id == shop.id)).all()}
    customers = [{"id": c.id, "name": c.name, "balance": get_balance(db, c.id), "trust": c.trust_score,
                  "paused": c.paused, "opt_in": c.message_opt_in, "lang": c.preferred_language}
                 for c in db.scalars(select(Customer).where(Customer.shop_id == shop.id).order_by(Customer.id)).all()]
    outbox = db.scalars(select(OutboxMessage).where(OutboxMessage.shop_id == shop.id)
                        .order_by(OutboxMessage.id.desc()).limit(40)).all()
    approvals = db.scalars(select(Approval).where(Approval.shop_id == shop.id, Approval.status == "PENDING")
                           .order_by(Approval.id.desc()).limit(40)).all()
    commits = db.scalars(select(Commitment).where(Commitment.shop_id == shop.id)
                         .order_by(Commitment.id.desc()).limit(20)).all()
    alert_rows = db.scalars(select(ActionAudit).where(ActionAudit.shop_id == shop.id, ActionAudit.tool == "shop_alert")
                            .order_by(ActionAudit.id.desc()).limit(15)).all()
    return {
        "shop": shop.name, "now": clock.now().isoformat(), "offset_days": round(clock.offset_days(), 2),
        "customers": customers,
        "outbox": [{"id": m.id, "dir": m.direction, "channel": m.channel, "customer": names.get(m.customer_id),
                    "text": m.text, "link": m.link, "label": m.label, "at": m.created_at.isoformat()} for m in outbox],
        "approvals": [{"id": a.id, "kind": a.kind, "customer": names.get(a.customer_id), "payload": a.payload}
                      for a in approvals],
        "commitments": [{"id": c.id, "customer": names.get(c.customer_id), "amount": c.amount,
                         "due_at": c.due_at.isoformat(), "state": c.state} for c in commits],
        "alerts": [{"id": a.id, "text": a.arguments.get("text", "")} for a in alert_rows],
    }


# Auto-run the scheduler in the real app. Tests set ARTHIQ_SCHEDULER=0.
if os.getenv("ARTHIQ_SCHEDULER", "1") != "0":
    from app.jobs import scheduler as _sched
    _sched.start()