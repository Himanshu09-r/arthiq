"""Dashboard API: inbox, audit log, voice approval, /dashboard page."""
import importlib
import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy import distinct, select
from sqlalchemy.orm import Session

from app.db.models import ActionAudit, Approval, Customer, Shop
from app.db.session import get_db
from app.engine import inbox, orders

router = APIRouter()
WEB = Path(__file__).resolve().parents[2] / "web"


def _shop(db) -> Shop:
    shop = db.scalars(select(Shop).order_by(Shop.id)).first()
    if shop is None:
        raise HTTPException(404, "no shop")
    return shop


class ActIn(BaseModel):
    action: str


def _item(db, a: Approval) -> dict:
    cust = db.get(Customer, a.customer_id) if a.customer_id else None
    p = a.payload or {}
    return {"id": a.id, "kind": a.kind, "customer": cust.name if cust else None,
            "summary": inbox.describe(db, a), "status": a.status,
            "at": a.created_at.isoformat(), "actions": inbox.actions_for(a) if a.status == "PENDING" else [],
            "message": p.get("message") if a.kind == "supplier_order" else None,
            "total": p.get("total") if a.kind == "supplier_order" else None,
            "decision": p.get("decision")}


@router.get("/dashboard")
def dashboard_page():
    return FileResponse(WEB / "dashboard.html")


@router.get("/inbox")
def inbox_list(db: Session = Depends(get_db)):
    shop = _shop(db)
    pend = db.scalars(select(Approval).where(
        Approval.shop_id == shop.id, Approval.status == "PENDING").order_by(Approval.id.desc())).all()
    done = db.scalars(select(Approval).where(
        Approval.shop_id == shop.id, Approval.status != "PENDING").order_by(Approval.id.desc()).limit(10)).all()
    return {"pending": [_item(db, a) for a in pend], "recent": [_item(db, a) for a in done]}


@router.post("/inbox/{approval_id}/act")
def inbox_act(approval_id: int, body: ActIn, db: Session = Depends(get_db)):
    return inbox.act(db, approval_id, body.action)


@router.post("/inbox/{approval_id}/voice")
async def inbox_voice(approval_id: int, audio: UploadFile = File(...), db: Session = Depends(get_db)):
    a = db.get(Approval, approval_id)
    if a is None or a.status != "PENDING":
        return {"status": "not_pending"}
    if a.kind != "supplier_order":
        return {"status": "voice_not_supported"}
    data = await audio.read()
    try:
        stt = importlib.import_module("app.voice.stt")
        transcript, _lang = stt.transcribe(data)
    except Exception as e:
        raise HTTPException(503, f"speech unavailable: {e}")
    res = orders.answer(db, approval_id, transcript)
    return {"transcript": transcript, **res}


@router.get("/audit")
def audit(limit: int = 100, tool: Optional[str] = None, actor: Optional[str] = None,
          q: Optional[str] = None, db: Session = Depends(get_db)):
    shop = _shop(db)
    limit = max(1, min(limit, 500))
    stmt = select(ActionAudit).where(ActionAudit.shop_id == shop.id)
    if tool:
        stmt = stmt.where(ActionAudit.tool == tool)
    if actor:
        stmt = stmt.where(ActionAudit.actor == actor)
    rows = db.scalars(stmt.order_by(ActionAudit.id.desc()).limit(500)).all()
    out = []
    for r in rows:
        args = json.dumps(r.arguments or {}, ensure_ascii=False, default=str)
        if q and q.lower() not in f"{r.rule_decision} {args}".lower():
            continue
        out.append({"id": r.id, "at": r.timestamp.isoformat(), "actor": r.actor, "tool": r.tool,
                    "decision": r.rule_decision, "approved_by": r.approved_by,
                    "args": args if len(args) <= 400 else args[:400] + "…"})
        tools = sorted(x for x in db.scalars(select(ActionAudit.tool).where(ActionAudit.shop_id == shop.id).distinct()).all() if x)
        actors = sorted(x for x in db.scalars(select(ActionAudit.actor).where(ActionAudit.shop_id == shop.id).distinct()).all() if x)
    return {"rows": out[:limit], "tools": tools, "actors": actors}