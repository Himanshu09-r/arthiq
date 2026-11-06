"""Payment webhook logic. Idempotent by gateway_ref. Money moves only through ledger_tools."""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import (ActionAudit, Approval, Customer, LedgerEntry,
                           OutboxMessage, Payment, Shop)
from app.engine import clock
from app.engine.alerts import push_alert
from app.engine.commitments import bump_trust, fulfil_if_paid
from app.tools.ledger_tools import ToolError, get_balance, record_payment
from app.voice.templates_collect import cx


def _held(db, shop, gateway_ref, amount, reason, now, customer_id=None, entry_id=None):
    db.add(Payment(shop_id=shop.id, customer_id=customer_id, entry_id=entry_id,
                   gateway_ref=gateway_ref, amount=amount, status="HELD", received_at=now))
    db.add(Approval(shop_id=shop.id, kind="held_payment", customer_id=customer_id, entry_id=entry_id,
                    payload={"gateway_ref": gateway_ref, "amount": amount, "reason": reason},
                    created_at=now))
    push_alert(db, shop, "pay_held", now=now, amount=amount)
    db.add(ActionAudit(shop_id=shop.id, actor="webhook", tool="payment_webhook",
                       arguments={"gateway_ref": gateway_ref, "amount": amount},
                       rule_decision=f"held:{reason}", timestamp=now))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate"}
    return {"status": "held", "reason": reason}


def handle_payment(db, shop_id, gateway_ref, amount, entry_id=None, customer_id=None, now=None) -> dict:
    now = now or clock.now()
    shop = db.get(Shop, shop_id)
    gateway_ref = (gateway_ref or "").strip()
    if not gateway_ref:
        return {"status": "rejected", "reason": "no_gateway_ref"}
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return {"status": "rejected", "reason": "bad_amount"}
    if amount <= 0:
        return {"status": "rejected", "reason": "bad_amount"}

    prev = db.scalar(select(Payment).where(Payment.gateway_ref == gateway_ref))
    if prev:
        return {"status": "duplicate", "first_status": prev.status, "amount": prev.amount}

    entry = cust = None
    if entry_id is not None:
        entry = db.get(LedgerEntry, entry_id)
        if entry is None or entry.shop_id != shop_id or entry.type != "credit":
            return _held(db, shop, gateway_ref, amount, "entry_not_found", now)
        cust = db.get(Customer, entry.customer_id)
    elif customer_id is not None:
        cust = db.get(Customer, customer_id)
        if cust is None or cust.shop_id != shop_id:
            return _held(db, shop, gateway_ref, amount, "customer_not_found", now)
    else:
        return _held(db, shop, gateway_ref, amount, "no_match", now)

    balance_before = get_balance(db, cust.id)
    applied = min(amount, max(balance_before, 0))
    extra = amount - applied
    if applied > 0:
        try:
            record_payment(db, shop_id, cust.id, applied, request_id="pay-" + gateway_ref)
        except ToolError as e:
            db.rollback()
            return _held(db, db.get(Shop, shop_id), gateway_ref, amount,
                         f"tool_error:{getattr(e, 'code', 'unknown')}", now, cust.id,
                         entry.id if entry else None)
    balance_after = get_balance(db, cust.id)

    db.add(Payment(shop_id=shop_id, customer_id=cust.id, entry_id=entry.id if entry else None,
                   gateway_ref=gateway_ref, amount=amount,
                   status="ADVANCE" if extra else "APPLIED", received_at=now))
    if extra:
        db.add(Approval(shop_id=shop_id, kind="held_payment", customer_id=cust.id,
                        entry_id=entry.id if entry else None,
                        payload={"gateway_ref": gateway_ref, "reason": "advance", "extra": extra},
                        created_at=now))
    if applied > 0 and balance_after <= 0:
        bump_trust(cust, 2)
    fulfil_if_paid(db, cust.id, now)

    if extra:
        push_alert(db, shop, "pay_adv", now=now, name=cust.name, amount=amount, extra=extra)
    elif balance_after <= 0:
        push_alert(db, shop, "pay_full", now=now, name=cust.name, amount=amount)
    else:
        push_alert(db, shop, "pay_part", now=now, name=cust.name, amount=amount, balance=balance_after)

    if cust.message_opt_in:   # receipt to customer (simulated WhatsApp)
        db.add(OutboxMessage(
            shop_id=shop_id, customer_id=cust.id, entry_id=entry.id if entry else None,
            direction="out", channel="whatsapp",
            text=cx(cust.preferred_language, "rcpt", cust=cust.name.split()[0], shop=shop.name,
                    amount=applied or amount, balance=max(balance_after, 0)),
            label="receipt", created_at=now))
    db.add(ActionAudit(shop_id=shop_id, actor="webhook", tool="payment_webhook",
                       arguments={"gateway_ref": gateway_ref, "amount": amount, "applied": applied,
                                  "extra": extra, "customer_id": cust.id},
                       rule_decision="applied", timestamp=now))
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return {"status": "duplicate"}
    return {"status": "applied", "applied": applied, "extra": extra,
            "balance_after": balance_after, "customer_id": cust.id}