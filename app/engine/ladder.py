"""Reminder ladder: due, +3, +7, +14, escalate at +21.
plan() only reads. run_ladder() applies guardrails and records what happens.
4b will add: write the message, create the payment link, mark SENT."""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.db.models import (ActionAudit, Approval, Commitment, Customer,
                           LedgerEntry, Reminder, Shop)
from app.engine import clock
from app.engine.guardrails import check_reminder, log_decision

LADDER = [0, 3, 7, 14, 21]
ESCALATE_STEP = 21
VOICE_STEP = 7


@dataclass
class Planned:
    entry_id: int
    customer_id: int
    step: int
    channel: str
    days_overdue: int
    amount: int


def outstanding(entry) -> int:
    return entry.amount - entry.paid_amount


def current_step(days_overdue: int) -> Optional[int]:
    steps = [s for s in LADDER if s <= days_overdue]
    return max(steps) if steps else None


def channel_for(step: int, shop) -> str:
    if step == ESCALATE_STEP:
        return "none"
    if step == VOICE_STEP and shop.calls_allowed:
        return "voice"
    return "whatsapp"   # +7 falls back to WhatsApp (with split offer) if calls not allowed


def plan(db, shop_id: int, now: datetime) -> list[Planned]:
    shop = db.get(Shop, shop_id)
    today = now.date()
    entries = db.scalars(select(LedgerEntry).where(
        LedgerEntry.shop_id == shop_id,
        LedgerEntry.type == "credit",
        LedgerEntry.status.in_(["OPEN", "PARTIAL"]),
        LedgerEntry.due_date.is_not(None),
        LedgerEntry.due_date <= today)).all()
    out: list[Planned] = []
    for e in entries:
        if outstanding(e) <= 0:
            continue
        days = (today - e.due_date).days
        step = current_step(days)
        if step is None:
            continue
        already = db.scalar(select(Reminder.id).where(
            Reminder.entry_id == e.id, Reminder.ladder_step == step).limit(1))
        if already:
            continue
        promise = db.scalar(select(Commitment.id).where(
            Commitment.customer_id == e.customer_id,
            Commitment.state == "PENDING",
            Commitment.due_at > now).limit(1))
        if promise:
            continue   # waiting for a promised date; ladder resumes after it passes
        out.append(Planned(e.id, e.customer_id, step, channel_for(step, shop), days, outstanding(e)))
    return out


def _escalate(db, shop_id, entry, cust, p: Planned, now):
    db.add(Reminder(shop_id=shop_id, entry_id=entry.id, customer_id=cust.id,
                    ladder_step=p.step, channel="none", language=cust.preferred_language,
                    status="ESCALATED", created_at=now))
    db.add(Approval(shop_id=shop_id, kind="escalation", customer_id=cust.id, entry_id=entry.id,
                    payload={"amount": p.amount, "days_overdue": p.days_overdue,
                             "suggestions": ["pause_credit", "lower_limit", "visit_in_person"]},
                    created_at=now))
    db.add(ActionAudit(shop_id=shop_id, actor="scheduler", tool="escalate_to_shopkeeper",
                       arguments={"entry_id": entry.id, "customer_id": cust.id,
                                  "days_overdue": p.days_overdue},
                       rule_decision="allowed", timestamp=now))


def _inbox_blocked(db, shop_id, entry, cust, p: Planned, decision, now):
    exists = db.scalar(select(Approval.id).where(
        Approval.kind == "blocked_reminder", Approval.entry_id == entry.id,
        Approval.status == "PENDING").limit(1))
    if exists:
        return
    db.add(Approval(shop_id=shop_id, kind="blocked_reminder", customer_id=cust.id,
                    entry_id=entry.id,
                    payload={"step": p.step, "reason": decision.reason, "amount": p.amount},
                    created_at=now))


def run_ladder(db, shop_id: int, now: Optional[datetime] = None) -> list[dict]:
    now = now or clock.now()
    shop = db.get(Shop, shop_id)
    results: list[dict] = []
    for p in plan(db, shop_id, now):
        entry = db.get(LedgerEntry, p.entry_id)
        cust = db.get(Customer, p.customer_id)
        row = {"entry_id": p.entry_id, "customer": cust.name, "step": p.step,
               "channel": p.channel, "verdict": "", "reason": "", "resume_at": None}

        if p.channel == "none":                      # day 21: tell the shopkeeper
            _escalate(db, shop_id, entry, cust, p, now)
            row.update(verdict="escalate", reason="day_21")
            results.append(row)
            continue

        d = check_reminder(db, shop, cust, entry, p.channel, now)
        log_decision(db, shop_id, cust, entry, p.step, p.channel, d, now)
        row.update(verdict=d.verdict, reason=d.reason,
                   resume_at=d.resume_at.isoformat() if d.resume_at else None)
        if d.verdict == "allow":
            db.add(Reminder(shop_id=shop_id, entry_id=entry.id, customer_id=cust.id,
                            ladder_step=p.step, channel=p.channel,
                            language=cust.preferred_language, status="READY", created_at=now))
        elif d.verdict == "block":
            _inbox_blocked(db, shop_id, entry, cust, p, d, now)
        results.append(row)
    db.commit()
    return results