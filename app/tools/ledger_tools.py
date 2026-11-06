import hashlib
import json
from datetime import date, datetime, timedelta
from sqlalchemy import select, func
from app.db.models import Shop, Customer, Item, LedgerEntry, IdempotencyKey, ActionAudit, TransactionItem
from app.engine.stock_movement import record_movement


class ToolError(Exception):
    """Expected failure with a machine code (later turned into a spoken
    message in the shop's language)."""
    def __init__(self, code, **info):
        super().__init__(code)
        self.code = code
        self.info = info


def make_key(*parts) -> str:
    raw = json.dumps(parts, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _audit(db, shop_id, tool, args, decision="allowed"):
    db.add(ActionAudit(shop_id=shop_id, actor="agent", tool=tool,
                       arguments=args, rule_decision=decision))


def get_balance(db, customer_id) -> int:
    def total(kind):
        return db.scalar(select(func.coalesce(func.sum(LedgerEntry.amount), 0)).where(
            LedgerEntry.customer_id == customer_id, LedgerEntry.type == kind))
    return total("credit") - total("payment")


def _customer(db, shop_id, customer_id):
    c = db.get(Customer, customer_id)
    if not c or c.shop_id != shop_id:
        raise ToolError("customer_not_found")
    return c


def _credit_result(db, entry, replay):
    stock_left = {}
    for ln in entry.items_json:
        item = db.get(Item, ln["item_id"])
        stock_left[item.name] = item.stock_qty
    return {"entry_id": entry.id, "total": entry.amount,
            "balance": get_balance(db, entry.customer_id),
            "due_date": entry.due_date.isoformat(),
            "stock_left": stock_left, "replay": replay}


def add_credit(db, shop_id, customer_id, lines, request_id):
    """lines = [{"item_id": 1, "qty": 2}, ...]. One transaction, safe to retry."""
    key = make_key("add_credit", shop_id, customer_id, lines, request_id)
    done = db.get(IdempotencyKey, key)
    if done:
        return _credit_result(db, db.get(LedgerEntry, done.result_ref), replay=True)

    shop = db.get(Shop, shop_id)
    customer = _customer(db, shop_id, customer_id)
    if not lines:
        raise ToolError("no_items")

    total, items_json, picked = 0, [], []
    for ln in lines:
        item = db.get(Item, ln["item_id"])
        qty = float(ln["qty"])
        if not item or item.shop_id != shop_id:
            raise ToolError("item_not_found")
        if qty <= 0:
            raise ToolError("bad_quantity")
        if item.stock_qty < qty:
            raise ToolError("low_stock", item=item.name, have=item.stock_qty)
        line_total = round(item.price * qty)
        total += line_total
        items_json.append({"item_id": item.id, "name": item.name, "qty": qty,
                           "unit": item.unit, "price": item.price, "line_total": line_total})
        picked.append((item, qty))

    if get_balance(db, customer_id) + total > customer.credit_limit:
        raise ToolError("credit_limit_exceeded", limit=customer.credit_limit)

    entry = LedgerEntry(shop_id=shop_id, customer_id=customer_id, type="credit",
                        amount=total, items_json=items_json,
                        due_date=date.today() + timedelta(days=shop.credit_days))
    db.add(entry)
    db.flush()

    for item, qty in picked:
        mov = record_movement(
            db,
            shop_id=shop_id,
            item_id=item.id,
            movement_type="STOCK_OUT",
            quantity=qty,
            unit=item.unit,
            source="ledger_credit",
            purchase_price=item.cost_price,
            reference_tx_id=str(entry.id),
            idempotency_key=f"credit_{key}_{item.id}",
            audit_info={"customer_id": customer_id, "entry_id": entry.id},
            actor="agent"
        )
        db.add(TransactionItem(
            shop_id=shop_id,
            ledger_entry_id=entry.id,
            item_id=item.id,
            quantity=qty,
            unit=item.unit,
            unit_price=item.price,
            line_total=round(item.price * qty),
            inventory_movement_id=mov.id
        ))

    db.add(IdempotencyKey(key=key, result_ref=entry.id))
    _audit(db, shop_id, "add_credit", {"customer_id": customer_id, "lines": lines, "total": total})
    db.commit()
    return _credit_result(db, entry, replay=False)


def record_payment(db, shop_id, customer_id, amount, request_id):
    key = make_key("record_payment", shop_id, customer_id, amount, request_id)
    done = db.get(IdempotencyKey, key)
    if done:
        e = db.get(LedgerEntry, done.result_ref)
        return {"entry_id": e.id, "paid": e.amount,
                "balance": get_balance(db, customer_id), "replay": True}

    _customer(db, shop_id, customer_id)
    if amount <= 0:
        raise ToolError("bad_amount")
    balance = get_balance(db, customer_id)
    if amount > balance:
        raise ToolError("payment_exceeds_balance", balance=balance)

    entry = LedgerEntry(shop_id=shop_id, customer_id=customer_id, type="payment",
                        amount=amount, status="PAID")
    db.add(entry)
    db.flush()

    left = amount  # apply to oldest unpaid credits first
    credits = db.scalars(select(LedgerEntry).where(
        LedgerEntry.customer_id == customer_id, LedgerEntry.type == "credit",
        LedgerEntry.paid_amount < LedgerEntry.amount
    ).order_by(LedgerEntry.created_at, LedgerEntry.id)).all()
    for c in credits:
        if left <= 0:
            break
        pay = min(c.amount - c.paid_amount, left)
        c.paid_amount += pay
        c.status = "PAID" if c.paid_amount >= c.amount else "PARTIAL"
        left -= pay

    db.add(IdempotencyKey(key=key, result_ref=entry.id))
    _audit(db, shop_id, "record_payment", {"customer_id": customer_id, "amount": amount})
    db.commit()
    return {"entry_id": entry.id, "paid": amount,
            "balance": get_balance(db, customer_id), "replay": False}


def stock_in(db, shop_id, item_id, qty, request_id):
    key = make_key("stock_in", shop_id, item_id, qty, request_id)
    item = db.get(Item, item_id)
    if not item or item.shop_id != shop_id:
        raise ToolError("item_not_found")
    if qty <= 0:
        raise ToolError("bad_quantity")
    if db.get(IdempotencyKey, key):
        return {"item": item.name, "stock_qty": item.stock_qty, "replay": True}

    record_movement(
        db,
        shop_id=shop_id,
        item_id=item.id,
        movement_type="STOCK_IN",
        quantity=qty,
        unit=item.unit,
        source="manual_stock_in",
        purchase_price=item.cost_price,
        reference_tx_id=str(request_id),
        idempotency_key=key,
        audit_info={"request_id": request_id},
        actor="shopkeeper"
    )
    db.add(IdempotencyKey(key=key, result_ref=item.id))
    db.commit()
    return {"item": item.name, "stock_qty": item.stock_qty, "replay": False}
    

def add_credit_amount(db, shop_id, customer_id, amount, request_id):
    """Credit by amount only (no items, no stock change)."""
    key = make_key("add_credit_amount", shop_id, customer_id, amount, request_id)
    done = db.get(IdempotencyKey, key)
    if done:
        e = db.get(LedgerEntry, done.result_ref)
        return {"entry_id": e.id, "total": e.amount,
                "balance": get_balance(db, customer_id), "replay": True}
    shop = db.get(Shop, shop_id)
    customer = _customer(db, shop_id, customer_id)
    if amount <= 0:
        raise ToolError("bad_amount")
    if get_balance(db, customer_id) + amount > customer.credit_limit:
        raise ToolError("credit_limit_exceeded", limit=customer.credit_limit)
    entry = LedgerEntry(shop_id=shop_id, customer_id=customer_id, type="credit",
                        amount=amount, items_json=[],
                        due_date=date.today() + timedelta(days=shop.credit_days))
    db.add(entry)
    db.flush()
    db.add(IdempotencyKey(key=key, result_ref=entry.id))
    _audit(db, shop_id, "add_credit_amount", {"customer_id": customer_id, "amount": amount})
    db.commit()
    return {"entry_id": entry.id, "total": amount,
            "balance": get_balance(db, customer_id), "replay": False}


def register_customer(db, shop_id, name, locality, phone, language, credit_limit, request_id):
    """Creates the customer record only. Credit is a separate operation."""
    from app.engine.customer_rules import find_duplicates   # lazy import avoids a cycle
    key = make_key("register_customer", shop_id, name, locality, phone, request_id)
    done = db.get(IdempotencyKey, key)
    if done:
        c = db.get(Customer, done.result_ref)
        return {"customer_id": c.id, "customer_code": c.customer_code, "replay": True}
    dups = find_duplicates(db, shop_id, name, locality, phone)
    if dups:
        raise ToolError("duplicate_customer", customer_id=dups[0].id)
    c = Customer(shop_id=shop_id, name=name, nicknames=[name.split()[0].lower()],
                 phone=phone, locality=locality, preferred_language=language,
                 credit_limit=credit_limit, created_at=datetime.now())
    db.add(c)
    db.flush()
    c.customer_code = f"CUST-{c.id:04d}"
    db.add(IdempotencyKey(key=key, result_ref=c.id))
    _audit(db, shop_id, "register_customer",
           {"customer_id": c.id, "name": name, "locality": locality, "language": language,
            "credit_limit": credit_limit})
    db.commit()
    return {"customer_id": c.id, "customer_code": c.customer_code, "replay": False}


def customer_history(db, shop_id, customer_id, limit=50):
    c = _customer(db, shop_id, customer_id)
    rows = db.scalars(select(LedgerEntry).where(LedgerEntry.customer_id == customer_id)
                      .order_by(LedgerEntry.created_at.desc(), LedgerEntry.id.desc())
                      .limit(limit)).all()
    entries = [{
        "id": e.id, "date": e.created_at.strftime("%d %b %Y %H:%M"), "type": e.type,
        "amount": e.amount, "status": e.status,
        "due_date": e.due_date.isoformat() if e.due_date else None,
        "items": ", ".join(f"{l['qty']:g} {l['unit']} {l['name']}" for l in (e.items_json or [])),
    } for e in rows]
    return {"customer": {"id": c.id, "name": c.name, "locality": c.locality,
                         "phone": c.phone, "customer_code": c.customer_code,
                         "language": c.preferred_language, "credit_limit": c.credit_limit},
            "balance": get_balance(db, customer_id), "entries": entries}
