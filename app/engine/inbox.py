"""Approval inbox actions. Deterministic, audited, idempotent (only PENDING items can be acted on).
Money never moves here. Opt-out (consent) can never be overridden."""
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.db.models import ActionAudit, Approval, Commitment, Customer
from app.engine import clock, orders
from app.engine.replies import resolve_approval
from app.tools.ledger_tools import get_balance

LABELS = {
    "approve": ("Approve & send (simulated)", "g"),
    "reject": ("Reject", "r"),
    "pause_reminders": ("Pause reminders", "o"),
    "freeze_credit": ("Freeze credit", "r"),
    "visit": ("I'll visit in person", ""),
    "dismiss": ("Dismiss", "x"),
    "resolve": ("Resolve dispute", "g"),
    "ack": ("Mark reviewed", ""),
    "not_received": ("Not received", "r"),
    "unpause": ("Unpause customer", "o"),
}

BASE = {
    "supplier_order": ["approve", "reject"],
    "escalation": ["pause_reminders", "freeze_credit", "visit", "dismiss"],
    "dispute": ["resolve"],
    "held_payment": ["ack"],
    "blocked_reminder": ["dismiss"],
    "claimed_paid": ["not_received", "ack"],
    "customer_reply": ["dismiss"],
}


def action_ids(a: Approval) -> list[str]:
    ids = list(BASE.get(a.kind, ["dismiss"]))
    if a.kind == "blocked_reminder" and (a.payload or {}).get("reason") == "customer_paused":
        ids.insert(0, "unpause")
    return ids


def actions_for(a: Approval) -> list[dict]:
    return [{"id": i, "label": LABELS[i][0], "style": LABELS[i][1]} for i in action_ids(a)]


def describe(db, a: Approval) -> str:
    p = a.payload or {}
    cust = db.get(Customer, a.customer_id) if a.customer_id else None
    name = cust.name if cust else "Unknown"
    if a.kind == "escalation":
        return (f"{name} owes ₹{p.get('amount')} and is {p.get('days_overdue')} days overdue. "
                "Reminders have stopped. You decide the next step.")
    if a.kind == "dispute":
        return f"{name} disputes the balance: \"{p.get('text', '')}\". Messaging is stopped; the balance is unchanged."
    if a.kind == "held_payment":
        if p.get("reason") == "advance":
            return f"{name} paid ₹{p.get('extra')} more than owed (kept as advance)."
        return f"Payment of ₹{p.get('amount')} ({p.get('gateway_ref')}) was held: {p.get('reason')}."
    if a.kind == "blocked_reminder":
        return (f"Reminder to {name} (step +{p.get('step')}, ₹{p.get('amount')}) "
                f"was blocked by a rule: {p.get('reason')}.")
    if a.kind == "claimed_paid":
        return f"{name} says: \"{p.get('text', '')}\". Please check your UPI app."
    if a.kind == "customer_reply":
        return f"{name} replied: \"{p.get('text', '')}\""
    if a.kind == "supplier_order":
        return f"Supplier order draft, about ₹{p.get('total')}, {len(p.get('items') or [])} items. Nothing is sent until you approve."
    return a.kind


def act(db, approval_id: int, action: str, now: Optional[datetime] = None) -> dict:
    now = now or clock.now()
    a = db.get(Approval, approval_id)
    if a is None or a.status != "PENDING":
        return {"status": "not_pending"}
    if action not in action_ids(a):
        return {"status": "invalid_action"}

    if a.kind == "supplier_order":
        return orders.approve(db, approval_id, now) if action == "approve" else orders.reject(db, approval_id, now)
    if a.kind == "dispute":
        return resolve_approval(db, approval_id, now)

    cust = db.get(Customer, a.customer_id) if a.customer_id else None
    note = ""
    if action == "pause_reminders" and cust:
        cust.paused = True
        note = "reminders paused"
    elif action == "unpause" and cust:
        cust.paused = False
        note = "customer unpaused"
    elif action == "freeze_credit" and cust:
        cust.credit_limit = max(get_balance(db, cust.id), 0)
        note = f"credit limit set to {cust.credit_limit}"
    elif action == "not_received" and cust:
        for c in db.scalars(select(Commitment).where(
                Commitment.customer_id == cust.id, Commitment.state == "PENDING")).all():
            if (c.source_text or "").startswith("claimed paid:"):
                c.state, c.resolved_at = "CANCELLED", now
        note = "payment not received, reminders resume"

    a.status, a.decided_at = "DONE", now
    a.payload = {**(a.payload or {}), "decision": action}
    db.add(ActionAudit(shop_id=a.shop_id, actor="shopkeeper", tool="inbox_action",
                       arguments={"approval_id": a.id, "kind": a.kind, "action": action,
                                  "customer_id": a.customer_id, "note": note},
                       rule_decision="allowed", approved_by="shopkeeper", timestamp=now))
    db.commit()
    return {"status": "done", "kind": a.kind, "action": action, "note": note}