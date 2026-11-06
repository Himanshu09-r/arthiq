"""Supplier order draft. Template-built (no LLM, so quantities and prices cannot drift).
Nothing is sent until the shopkeeper approves. Sending is simulated in the demo."""
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.db.models import ActionAudit, Approval, Shop
from app.engine import clock
from app.engine.cash_guardian import cash_guardian
from app.voice.templates_cash import tc


def _build_message(shop, buy: list[dict], lang: str) -> str:
    lines = []
    for b in buy:
        if b["known_price"]:
            lines.append("• " + tc(lang, "ord_line", item=b["name"], qty=b["qty"], unit=b["unit"], price=b["unit_cost"]))
        else:
            lines.append("• " + tc(lang, "ord_line_np", item=b["name"], qty=b["qty"], unit=b["unit"]))
    return tc(lang, "ord_head", shop=shop.name) + "\n" + "\n".join(lines) + "\n" + tc(lang, "ord_tail")


def create_draft(db, shop_id: int, now: Optional[datetime] = None) -> dict:
    now = now or clock.now()
    shop = db.get(Shop, shop_id)
    g = cash_guardian(db, shop_id, now)
    if g.get("need_cash"):
        return {"status": "need_cash", "text": g["text"]}
    buy = g["buy"]
    if not buy:
        return {"status": "nothing_to_order"}
    lang = shop.language
    sig = [[b["item_id"], b["qty"]] for b in sorted(buy, key=lambda b: b["item_id"])]
    pending = db.scalars(select(Approval).where(
        Approval.shop_id == shop_id, Approval.kind == "supplier_order",
        Approval.status == "PENDING")).all()
    for p in pending:
        if p.payload.get("sig") == sig:               # same draft already waiting
            return {"status": "exists", "approval_id": p.id, "message": p.payload["message"],
                    "total": p.payload["total"],
                    "ask": tc(lang, "ord_ask", count=len(buy), total=p.payload["total"])}
    for p in pending:                                  # stale draft is replaced, never silently sent
        p.status, p.decided_at = "REJECTED", now
        db.add(ActionAudit(shop_id=shop_id, actor="system", tool="supplier_order_superseded",
                           arguments={"approval_id": p.id}, rule_decision="rejected", timestamp=now))
    total = sum(b["cost"] for b in buy)
    msg = _build_message(shop, buy, lang)
    a = Approval(shop_id=shop_id, kind="supplier_order", status="PENDING", created_at=now,
                 payload={"sig": sig, "items": buy, "total": total, "message": msg, "lang": lang})
    db.add(a)
    db.flush()
    db.add(ActionAudit(shop_id=shop_id, actor="agent", tool="supplier_order_draft",
                       arguments={"approval_id": a.id, "total": total, "items": len(buy)},
                       rule_decision="pending_approval", timestamp=now))
    db.commit()
    return {"status": "created", "approval_id": a.id, "message": msg, "total": total,
            "ask": tc(lang, "ord_ask", count=len(buy), total=total)}


def approve(db, approval_id: int, now: Optional[datetime] = None, by: str = "shopkeeper") -> dict:
    now = now or clock.now()
    a = db.get(Approval, approval_id)
    if a is None or a.kind != "supplier_order" or a.status != "PENDING":
        return {"status": "not_pending"}
    a.payload = {**a.payload, "sent_at": now.isoformat(), "sent_via": "simulated_whatsapp"}
    a.status, a.decided_at = "DONE", now
    db.add(ActionAudit(shop_id=a.shop_id, actor="shopkeeper", tool="supplier_send",
                       arguments={"approval_id": a.id, "message": a.payload["message"],
                                  "total": a.payload["total"]},
                       rule_decision="approved", approved_by=by, timestamp=now))
    db.commit()
    return {"status": "done", "message": a.payload["message"]}


def reject(db, approval_id: int, now: Optional[datetime] = None) -> dict:
    now = now or clock.now()
    a = db.get(Approval, approval_id)
    if a is None or a.kind != "supplier_order" or a.status != "PENDING":
        return {"status": "not_pending"}
    a.status, a.decided_at = "REJECTED", now
    db.add(ActionAudit(shop_id=a.shop_id, actor="shopkeeper", tool="supplier_order_rejected",
                       arguments={"approval_id": a.id}, rule_decision="rejected",
                       approved_by="shopkeeper", timestamp=now))
    db.commit()
    return {"status": "rejected"}


def _yes_no(text: str, lang: str):
    from app.voice import templates as T
    try:
        return T.is_yes(text, lang), T.is_no(text, lang)
    except TypeError:
        return T.is_yes(text), T.is_no(text)


def answer(db, approval_id: int, text: str, now: Optional[datetime] = None) -> dict:
    """Shopkeeper's spoken (or typed) yes/no for a pending order. 'no' wins; unclear changes nothing."""
    a = db.get(Approval, approval_id)
    if a is None or a.status != "PENDING":
        return {"status": "not_pending"}
    lang = db.get(Shop, a.shop_id).language
    yes, no = _yes_no(text or "", lang)
    if no:
        return reject(db, approval_id, now)
    if yes:
        return approve(db, approval_id, now)
    return {"status": "unclear"}