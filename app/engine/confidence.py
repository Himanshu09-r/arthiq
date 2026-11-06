from dataclasses import dataclass, field
from typing import Optional
from app.db.models import Customer
from app.engine.matching import match_customer, match_item
from app.tools.ledger_tools import get_balance
from app.voice.templates import item_label, fmt
from app.engine.customer_rules import display_name


@dataclass
class Validation:
    status: str                          # ready | ask | error
    action: Optional[str] = None         # add_credit_items | add_credit_amount | record_payment
    customer: Optional[Customer] = None
    lines: list = field(default_factory=list)
    amount: Optional[int] = None
    total: Optional[int] = None
    balance_after: Optional[int] = None
    code: Optional[str] = None           # template key for ask/error
    info: dict = field(default_factory=dict)


def _err(code, **info):
    return Validation("error", code=code, info=info)


def validate(db, shop_id, ex, lang, forced_customer=None) -> Validation:
    if ex.intent not in ("add_credit", "record_payment"):
        return _err("err_generic")

    if forced_customer:
        cust = forced_customer
    else:
        if not ex.customer_ref:
            return _err("err_generic")
        res, found = match_customer(db, shop_id, ex.customer_ref)
        if res == "none":
            return _err("err_customer_unknown", name=ex.customer_ref)
        if res == "ambiguous":
            first = ex.customer_ref.split()[0]
            return Validation("ask", code="which_customer", info={
                "name": first,
                "options": " / ".join(display_name(c) for c in found),
                "candidates": [(c.id, display_name(c)) for c in found]})
        cust = found[0]

    balance = get_balance(db, cust.id)

    if ex.intent == "record_payment":
        if not ex.amount or ex.amount <= 0:
            return _err("err_generic")
        if ex.amount > balance:
            return _err("err_overpay", balance=balance)
        return Validation("ready", action="record_payment", customer=cust,
                          amount=ex.amount, balance_after=balance - ex.amount)

    # add_credit
    lines, total = [], 0
    if ex.items:
        for it in ex.items:
            item = match_item(db, shop_id, it.name)
            if not item:
                return _err("err_item_unknown", name=it.name)
            if it.qty <= 0:
                return _err("err_generic")
            if item.stock_qty < it.qty:
                return _err("err_low_stock", item=item_label(item, lang),
                            have=fmt(item.stock_qty))
            total += round(item.price * it.qty)      # price comes from the DB, never the LLM
            lines.append({"item_id": item.id, "qty": it.qty, "unit": item.unit,
                          "label": item_label(item, lang)})
        action = "add_credit_items"
    elif ex.amount and ex.amount > 0:
        total, action = ex.amount, "add_credit_amount"
    else:
        return _err("err_generic")

    if balance + total > cust.credit_limit:
        return _err("err_limit", limit=cust.credit_limit)
    return Validation("ready", action=action, customer=cust, lines=lines,
                      total=total, balance_after=balance + total)