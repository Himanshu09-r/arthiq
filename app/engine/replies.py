"""Customer reply handling + approval resolution. Money never moves here."""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select

from app.agent.classify_reply import classify
from app.db.models import (ActionAudit, Approval, Commitment, Customer, LedgerEntry,
                           OutboxMessage, Reminder, Shop)
from app.engine import clock
from app.engine.alerts import push_alert
from app.engine.commitments import create_commitment
from app.engine.ladder import outstanding
from app.voice.dates import resolve_date


def _open_entries(db, cust_id):
    rows = db.scalars(select(LedgerEntry).where(
        LedgerEntry.customer_id == cust_id, LedgerEntry.type == "credit",
        LedgerEntry.status.in_(["OPEN", "PARTIAL"])).order_by(LedgerEntry.due_date, LedgerEntry.id)).all()
    return [e for e in rows if outstanding(e) > 0]


def _target_entry(db, cust):
    entries = _open_entries(db, cust.id)
    if not entries:
        return None
    last = db.scalar(select(Reminder).where(
        Reminder.customer_id == cust.id, Reminder.entry_id.in_([e.id for e in entries])
    ).order_by(Reminder.id.desc()).limit(1))
    return db.get(LedgerEntry, last.entry_id) if last else entries[0]


def _cancel_ready(db, cust_id, why):
    for r in db.scalars(select(Reminder).where(
            Reminder.customer_id == cust_id, Reminder.status == "READY")).all():
        r.status, r.outcome = "CANCELLED", why


def _default_due(now, days):
    return (now + timedelta(days=days)).replace(hour=18, minute=0, second=0, microsecond=0)


def handle_reply(db, shop_id: int, customer_id: int, text: str, now: Optional[datetime] = None) -> dict:
    now = now or clock.now()
    shop = db.get(Shop, shop_id)
    cust = db.get(Customer, customer_id)
    if cust is None or cust.shop_id != shop_id:
        raise ValueError("customer_not_found")
    text = (text or "").strip()
    inbound = OutboxMessage(shop_id=shop_id, customer_id=cust.id, direction="in",
                            channel="whatsapp", text=text, created_at=now)
    db.add(inbound)

    c = classify(text, now)
    label = c["label"]
    inbound.label = label
    entry = _target_entry(db, cust)
    result = {"label": label, "source": c.get("source"), "action": "none", "alert": None}

    if label == "stop":
        cust.message_opt_in = False
        _cancel_ready(db, cust.id, "opted_out")
        result["action"] = "opted_out"

    elif label == "dispute":
        entries = _open_entries(db, cust.id)
        for e in entries:
            e.status = "DISPUTED"       # balance untouched
        for cm in db.scalars(select(Commitment).where(
                Commitment.customer_id == cust.id, Commitment.state == "PENDING")).all():
            cm.state = "DISPUTED"
        _cancel_ready(db, cust.id, "dispute")
        db.add(Approval(shop_id=shop_id, kind="dispute", customer_id=cust.id,
                        entry_id=entry.id if entry else None,
                        payload={"text": text, "entries": [e.id for e in entries]}, created_at=now))
        result["alert"] = push_alert(db, shop, "dispute", now=now, name=cust.name)
        result["action"] = "disputed"

    elif label in ("promise", "time"):
        if entry is None:
            db.add(Approval(shop_id=shop_id, kind="customer_reply", customer_id=cust.id,
                            payload={"text": text, "note": "nothing due"}, created_at=now))
            result["action"] = "no_open_entry"
        else:
            due = resolve_date(c.get("date_text"), now) or resolve_date(text, now)
            defaulted = due is None
            if defaulted:
                due = _default_due(now, 2 if label == "promise" else 3)
            cm = create_commitment(db, shop, cust, entry, due, text, now)
            result.update(action="commitment", due_at=due.isoformat(), defaulted=defaulted,
                          commitment_id=None)
            db.flush()
            result["commitment_id"] = cm.id

    elif label == "paid":
        db.add(Approval(shop_id=shop_id, kind="claimed_paid", customer_id=cust.id,
                        entry_id=entry.id if entry else None, payload={"text": text}, created_at=now))
        if entry is not None:     # pause the ladder for 2 days while the shopkeeper verifies
            create_commitment(db, shop, cust, entry, _default_due(now, 2), "claimed paid: " + text,
                              now, alert=False)
        result["alert"] = push_alert(db, shop, "claimed_paid", now=now, name=cust.name)
        result["action"] = "claimed_paid"

    else:
        db.add(Approval(shop_id=shop_id, kind="customer_reply", customer_id=cust.id,
                        payload={"text": text}, created_at=now))
        result["action"] = "inbox"

    db.add(ActionAudit(shop_id=shop_id, actor="customer", tool="customer_reply",
                       arguments={"customer_id": cust.id, "label": label, "text": text[:200]},
                       rule_decision=result["action"], timestamp=now))
    db.commit()
    return result


def resolve_approval(db, approval_id: int, now: Optional[datetime] = None) -> dict:
    now = now or clock.now()
    a = db.get(Approval, approval_id)
    if a is None or a.status != "PENDING":
        return {"status": "not_pending"}
    if a.kind == "dispute" and a.customer_id:
        for e in db.scalars(select(LedgerEntry).where(
                LedgerEntry.customer_id == a.customer_id, LedgerEntry.status == "DISPUTED")).all():
            e.status = "PAID" if outstanding(e) <= 0 else ("PARTIAL" if e.paid_amount > 0 else "OPEN")
        for cm in db.scalars(select(Commitment).where(
                Commitment.customer_id == a.customer_id, Commitment.state == "DISPUTED")).all():
            cm.state, cm.resolved_at = "CANCELLED", now
    a.status, a.decided_at = "DONE", now
    db.add(ActionAudit(shop_id=a.shop_id, actor="shopkeeper", tool="resolve_approval",
                       arguments={"approval_id": a.id, "kind": a.kind}, rule_decision="allowed",
                       approved_by="shopkeeper", timestamp=now))
    db.commit()
    return {"status": "done", "kind": a.kind}