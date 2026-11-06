"""Sender: takes READY reminders, re-checks everything, writes the message, 'sends' to the outbox."""
from typing import Optional
from datetime import datetime

from sqlalchemy import select

from app.agent.write_message import write_reminder
from app.db.models import (ActionAudit, Approval, Commitment, Customer, LedgerEntry,
                           OutboxMessage, Reminder, Shop)
from app.engine import clock
from app.engine.guardrails import check_reminder, log_decision
from app.engine.ladder import outstanding
from app.integrations.paytm_mock import create_link


def _inbox_blocked(db, shop_id, cust, entry, r, reason, now):
    if db.scalar(select(Approval.id).where(Approval.kind == "blocked_reminder",
                                           Approval.entry_id == entry.id,
                                           Approval.status == "PENDING").limit(1)):
        return
    db.add(Approval(shop_id=shop_id, kind="blocked_reminder", customer_id=cust.id, entry_id=entry.id,
                    payload={"step": r.ladder_step, "reason": reason, "amount": outstanding(entry)},
                    created_at=now))


def send_ready(db, shop_id: int, now: Optional[datetime] = None) -> list[dict]:
    now = now or clock.now()
    shop = db.get(Shop, shop_id)
    rows = db.scalars(select(Reminder).where(
        Reminder.shop_id == shop_id, Reminder.status == "READY").order_by(Reminder.id)).all()
    out = []
    for r in rows:
        entry = db.get(LedgerEntry, r.entry_id)
        cust = db.get(Customer, r.customer_id)
        row = {"reminder_id": r.id, "customer": cust.name, "step": r.ladder_step, "result": ""}

        if entry.status == "PAID" or outstanding(entry) <= 0:
            r.status, r.outcome = "CANCELLED", "paid_before_send"
            row["result"] = "cancelled:paid_before_send"
            out.append(row)
            continue
        if r.ladder_step < 100 and db.scalar(select(Commitment.id).where(
                Commitment.customer_id == cust.id, Commitment.state == "PENDING",
                Commitment.due_at > now).limit(1)):
            r.status, r.outcome = "CANCELLED", "promise_pending"
            row["result"] = "cancelled:promise_pending"
            out.append(row)
            continue

        r.status = "SENDING"     # so the weekly-cap query does not count this reminder itself
        db.flush()
        d = check_reminder(db, shop, cust, entry, r.channel, now)
        log_decision(db, shop_id, cust, entry, r.ladder_step, r.channel, d, now)
        if d.verdict == "delay":
            r.status = "READY"
            row["result"] = f"delayed:{d.reason}"
            out.append(row)
            continue
        if d.verdict == "block":
            r.status, r.outcome = "CANCELLED", d.reason[:30]
            _inbox_blocked(db, shop_id, cust, entry, r, d.reason, now)
            row["result"] = f"blocked:{d.reason}"
            out.append(row)
            continue

        try:
            link = create_link(entry.id)
        except Exception:
            link = None          # send without link, retry link next run
        w = write_reminder(db, shop, cust, entry, r.ladder_step, link, now)
        r.message_text, r.status, r.sent_at = w["text"], "SENT", now
        r.outcome = f"sent_{w['source']}"
        db.add(OutboxMessage(shop_id=shop_id, customer_id=cust.id, entry_id=entry.id, reminder_id=r.id,
                             direction="out", channel=r.channel, text=w["text"], link=link,
                             label=f"step_{r.ladder_step}", created_at=now))
        db.add(ActionAudit(shop_id=shop_id, actor="sender", tool="send_reminder",
                           arguments={"reminder_id": r.id, "entry_id": entry.id, "step": r.ladder_step,
                                      "source": w["source"], "filter_reason": w["reason"]},
                           rule_decision="allowed", timestamp=now))
        row["result"] = f"sent:{w['source']}"
        out.append(row)
    db.commit()
    return out