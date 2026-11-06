"""Arthiq Memory: promises as a state machine PENDING -> FULFILLED | OVERDUE | DISPUTED | CANCELLED."""
from datetime import datetime

from sqlalchemy import select

from app.db.models import Commitment, Customer, LedgerEntry, Reminder, Shop
from app.engine.alerts import push_alert
from app.engine.ladder import current_step, outstanding
from app.tools.ledger_tools import get_balance


def bump_trust(cust, delta: int) -> None:
    cust.trust_score = max(0, min(100, (cust.trust_score or 50) + delta))


def create_commitment(db, shop, cust, entry, due_at: datetime, text: str, now: datetime,
                      alert: bool = True) -> Commitment:
    for old in db.scalars(select(Commitment).where(
            Commitment.customer_id == cust.id, Commitment.state == "PENDING")).all():
        old.state = "CANCELLED"
        old.resolved_at = now
    c = Commitment(shop_id=shop.id, customer_id=cust.id, entry_id=entry.id if entry else None,
                   amount=outstanding(entry) if entry else 0, due_at=due_at,
                   state="PENDING", source_text=text, created_at=now)
    db.add(c)
    if alert:
        push_alert(db, shop, "promise_new", now=now, name=cust.name, amount=c.amount,
                   day=due_at.day, mon=due_at.strftime("%B"))
    return c


def fulfil_if_paid(db, customer_id: int, now: datetime) -> None:
    cust = db.get(Customer, customer_id)
    for c in db.scalars(select(Commitment).where(
            Commitment.customer_id == customer_id, Commitment.state == "PENDING")).all():
        entry = db.get(LedgerEntry, c.entry_id) if c.entry_id else None
        if get_balance(db, customer_id) <= 0 or (entry is not None and outstanding(entry) <= 0):
            c.state = "FULFILLED"
            c.resolved_at = now
            bump_trust(cust, 3)


def _needs_followup(db, entry, now) -> bool:
    """True if the normal ladder will NOT produce a message right now (so we add one)."""
    if entry.due_date is None:
        return True
    step = current_step((now.date() - entry.due_date).days)
    if step is None:
        return True
    return db.scalar(select(Reminder.id).where(
        Reminder.entry_id == entry.id, Reminder.ladder_step == step).limit(1)) is not None


def check_promises(db, shop_id: int, now: datetime) -> list[dict]:
    shop = db.get(Shop, shop_id)
    due = db.scalars(select(Commitment).where(
        Commitment.shop_id == shop_id, Commitment.state == "PENDING",
        Commitment.due_at <= now).order_by(Commitment.id)).all()
    out = []
    for c in due:
        cust = db.get(Customer, c.customer_id)
        entry = db.get(LedgerEntry, c.entry_id) if c.entry_id else None
        paid = get_balance(db, c.customer_id) <= 0 or (entry is not None and outstanding(entry) <= 0)
        if paid:
            c.state = "FULFILLED"
            bump_trust(cust, 3)
        else:
            c.state = "OVERDUE"
            bump_trust(cust, -5)
            push_alert(db, shop, "promise_broken", now=now, name=cust.name,
                       amount=outstanding(entry) if entry else c.amount)
            if entry is not None and _needs_followup(db, entry, now):
                db.add(Reminder(shop_id=shop_id, entry_id=entry.id, customer_id=cust.id,
                                ladder_step=100 + c.id, channel="whatsapp",
                                language=cust.preferred_language, status="READY", created_at=now))
        c.resolved_at = now
        out.append({"commitment_id": c.id, "customer": cust.name, "state": c.state})
    db.commit()
    return out