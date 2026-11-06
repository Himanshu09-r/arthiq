"""Stock, cash, orders, briefing API + /insights page."""
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Approval, Shop
from app.db.session import get_db
from app.engine import clock, orders
from app.engine.briefing import briefing
from app.engine.cash_guardian import cash_guardian
from app.engine.stock import alerts, compute_stock, label, set_cash

router = APIRouter()
WEB = Path(__file__).resolve().parents[2] / "web"
_last_brief: dict = {}


def _shop(db) -> Shop:
    shop = db.scalars(select(Shop).order_by(Shop.id)).first()
    if shop is None:
        raise HTTPException(404, "no shop")
    return shop


def _audio(text: str, lang: str) -> Response:
    try:
        from app.voice.tts import speak
        return Response(speak(text, lang), media_type="audio/wav")
    except Exception as e:
        raise HTTPException(503, f"tts unavailable: {e}")


class CashIn(BaseModel):
    cash: Optional[int] = None
    payables: Optional[int] = None
    lead_time_days: Optional[int] = None


class AnswerIn(BaseModel):
    text: str


@router.get("/insights")
def insights_page():
    return FileResponse(WEB / "insights.html")


@router.get("/stock/status")
def stock_status(db: Session = Depends(get_db)):
    shop = _shop(db)
    rows = []
    for s in compute_stock(db, shop.id):
        it = s["item"]
        rows.append({"id": it.id, "name": label(it, shop.language), "stock": s["stock"], "unit": it.unit,
                     "daily": round(s["daily"], 1), "reorder_point": s["reorder_point"],
                     "days_left": None if s["days_left"] is None else round(s["days_left"], 1),
                     "low": s["low"], "near_expiry": s["near_expiry"], "expiry_days": s["expiry_days"],
                     "dead": s["dead"]})
    return {"items": rows, "alerts": alerts(db, shop.id, limit=3)}


@router.get("/stock/alerts/audio")
def stock_alerts_audio(db: Session = Depends(get_db)):
    shop = _shop(db)
    top = alerts(db, shop.id, limit=3)
    if not top:
        raise HTTPException(404, "no alerts")
    return _audio(" ".join(a["text"] for a in top), shop.language)


@router.post("/cash")
def cash_set(body: CashIn, db: Session = Depends(get_db)):
    cs = set_cash(db, _shop(db).id, body.cash, body.payables, body.lead_time_days)
    return {"cash": cs.cash, "payables": cs.payables, "lead_time_days": cs.lead_time_days}


@router.get("/cash/guardian")
def guardian(db: Session = Depends(get_db)):
    return cash_guardian(db, _shop(db).id)


@router.get("/cash/guardian/audio")
def guardian_audio(db: Session = Depends(get_db)):
    shop = _shop(db)
    return _audio(cash_guardian(db, shop.id)["text"], shop.language)


@router.post("/orders/draft")
def order_draft(db: Session = Depends(get_db)):
    return orders.create_draft(db, _shop(db).id)


@router.get("/orders/pending")
def orders_pending(db: Session = Depends(get_db)):
    shop = _shop(db)
    rows = db.scalars(select(Approval).where(
        Approval.shop_id == shop.id, Approval.kind == "supplier_order",
        Approval.status == "PENDING").order_by(Approval.id.desc())).all()
    return [{"id": a.id, "message": a.payload.get("message"), "total": a.payload.get("total"),
             "items": a.payload.get("items")} for a in rows]


@router.post("/approvals/{approval_id}/approve")
def approvals_approve(approval_id: int, db: Session = Depends(get_db)):
    return orders.approve(db, approval_id)


@router.post("/approvals/{approval_id}/reject")
def approvals_reject(approval_id: int, db: Session = Depends(get_db)):
    return orders.reject(db, approval_id)


@router.post("/approvals/{approval_id}/answer")
def approvals_answer(approval_id: int, body: AnswerIn, db: Session = Depends(get_db)):
    return orders.answer(db, approval_id, body.text)


@router.get("/briefing/today")
def briefing_today(smooth: int = 1, db: Session = Depends(get_db)):
    shop = _shop(db)
    b = briefing(db, shop.id, use_llm=bool(smooth))
    _last_brief[shop.id] = b
    return b


@router.get("/briefing/audio")
def briefing_audio(db: Session = Depends(get_db)):
    shop = _shop(db)
    b = _last_brief.get(shop.id) or briefing(db, shop.id, use_llm=False)
    return _audio(b["text"], b["lang"])