import uuid
from dataclasses import dataclass
from typing import Optional
from app.db.models import Shop, Customer
from app.agent.extract import extract
from app.agent.llm import chat_json, LLMError
from app.engine.confidence import validate
from app.engine.customer_rules import display_name
from app.engine.registration import check_registration
from app.voice.templates import say, is_yes, is_no, fmt
from app.tools import ledger_tools as L

ERR_MAP = {"low_stock": "err_low_stock", "credit_limit_exceeded": "err_limit",
           "payment_exceeds_balance": "err_overpay"}

FOLLOWUP_HINT = ("The shopkeeper was just asked what the newly registered customer took on "
                 "credit. If the reply lists items or an amount, intent is add_credit and "
                 "customer_ref is null.")


@dataclass
class Session:
    pending: Optional[dict] = None     # waiting for a yes (credit, payment or registration)
    awaiting: Optional[dict] = None    # waiting for "which Ramesh?"
    duplicate: Optional[dict] = None   # waiting for yes/no "use the existing customer?"
    followup: Optional[dict] = None    # customer just registered, waiting for "what did they take?"


SESSIONS: dict[int, Session] = {}       # in memory is enough for the demo; customers are in the DB


def _session(shop_id) -> Session:
    return SESSIONS.setdefault(shop_id, Session())


def _out(state, reply):
    return {"state": state, "reply": reply}


def _first(name: str) -> str:
    return name.split()[0] if name else name


def _reg_details(name, locality, phone) -> str:
    parts = [name]
    if locality:
        parts.append(locality)
    if phone:
        parts.append(" ".join(phone))      # digit by digit so TTS reads them clearly
    return ", ".join(parts)


def _pick_candidate(text, candidates):
    listing = "\n".join(f"{i + 1}. {name}" for i, (_, name) in enumerate(candidates))
    system = ("The shopkeeper was asked which person they meant. Options:\n" + listing +
              '\nThe answer may be in any Indian language. Reply with only JSON: '
              '{"choice": <option number or null if it matches none or more than one>}')
    try:
        n = chat_json(system, text, max_tokens=200).get("choice")
        if isinstance(n, int) and 1 <= n <= len(candidates):
            return candidates[n - 1][0]
    except LLMError:
        pass
    return None


# ---------- credit / payment ----------
def _handle_validation(db, shop, s, v, ex, lang, new_customer=False):
    if v.status == "ask":
        s.awaiting = {"extraction": ex, "candidates": v.info["candidates"]}
        return _out("ask", say(lang, v.code, **v.info))
    if v.status == "error":
        return _out("error", say(lang, v.code, **v.info))

    s.pending = {"action": v.action, "customer_id": v.customer.id, "name": v.customer.name,
                 "lines": v.lines, "amount": v.amount, "total": v.total,
                 "new_customer": new_customer, "request_id": uuid.uuid4().hex}
    if v.action == "add_credit_items":
        items = ", ".join(f"{fmt(l['qty'])} {l['unit']} {l['label']}" for l in v.lines)
        text = say(lang, "rb_credit_items", name=v.customer.name, total=v.total, items=items)
    elif v.action == "add_credit_amount":
        text = say(lang, "rb_credit_amount", name=v.customer.name, total=v.total)
    else:
        text = say(lang, "rb_payment", name=v.customer.name, amount=v.amount,
                   balance=v.balance_after)
    return _out("confirm", text)


# ---------- registration ----------
def _start_registration(db, shop, s, ex, lang):
    chk = check_registration(db, shop.id, ex.customer_ref, ex.locality, ex.phone,
                             ex.language, ex.credit_limit, lang)
    if chk.status == "error":
        return _out("error", say(lang, chk.code, **chk.info))
    then = None                                    # first purchase said in the same sentence
    if ex.items or ex.amount:
        then = ex.model_copy(update={"intent": "add_credit", "customer_ref": None})
    if chk.status == "duplicate":
        s.duplicate = {"customer_id": chk.duplicate.id, "then": then}
        return _out("ask", say(lang, "err_duplicate", details=display_name(chk.duplicate)))
    s.pending = {"action": "register_customer", "name": chk.name, "locality": chk.locality,
                 "phone": chk.phone, "language": chk.language, "credit_limit": chk.credit_limit,
                 "then": then, "request_id": uuid.uuid4().hex}
    return _out("confirm", say(lang, "rb_register", limit=chk.credit_limit,
                               details=_reg_details(chk.name, chk.locality, chk.phone)))


def _after_registration(db, shop, s, cust, then, lang):
    """Customer exists now. Continue to the first purchase (a separate DB operation)."""
    if then:
        v = validate(db, shop.id, then, lang, forced_customer=cust)
        if v.status == "ready":
            return _handle_validation(db, shop, s, v, then, lang, new_customer=True)
        s.followup = {"customer_id": cust.id, "name": cust.name}   # they can retry the items
        return _out("error", say(lang, "registered", name=cust.name) + " " +
                    say(lang, v.code, **v.info))
    s.followup = {"customer_id": cust.id, "name": cust.name}
    return _out("ask", say(lang, "ask_items", name=_first(cust.name)))


def _commit(db, shop, s, lang):
    p, s.pending = s.pending, None
    try:
        if p["action"] == "register_customer":
            r = L.register_customer(db, shop.id, p["name"], p["locality"], p["phone"],
                                    p["language"], p["credit_limit"], p["request_id"])
            return _after_registration(db, shop, s, db.get(Customer, r["customer_id"]),
                                       p.get("then"), lang)
        prefix = (say(lang, "registered", name=p["name"]) + " ") if p.get("new_customer") else ""
        if p["action"] == "add_credit_items":
            lines = [{"item_id": l["item_id"], "qty": l["qty"]} for l in p["lines"]]
            r = L.add_credit(db, shop.id, p["customer_id"], lines, p["request_id"])
            return _out("saved", prefix + say(lang, "saved_credit", name=p["name"],
                                              total=r["total"], balance=r["balance"]))
        if p["action"] == "add_credit_amount":
            r = L.add_credit_amount(db, shop.id, p["customer_id"], p["total"], p["request_id"])
            return _out("saved", prefix + say(lang, "saved_credit", name=p["name"],
                                              total=r["total"], balance=r["balance"]))
        r = L.record_payment(db, shop.id, p["customer_id"], p["amount"], p["request_id"])
        return _out("saved", say(lang, "saved_payment", name=p["name"],
                                 amount=p["amount"], balance=r["balance"]))
    except L.ToolError as e:
        if e.code == "duplicate_customer":
            c = db.get(Customer, e.info["customer_id"])
            s.duplicate = {"customer_id": c.id, "then": p.get("then")}
            return _out("ask", say(lang, "err_duplicate", details=display_name(c)))
        return _out("error", say(lang, ERR_MAP.get(e.code, "err_generic"), **e.info))


# ---------- main entry ----------
def handle(db, shop_id: int, text: str) -> dict:
    shop = db.get(Shop, shop_id)
    lang = shop.language
    s = _session(shop_id)

    if s.awaiting:                                   # answer to "which Ramesh?"
        aw, s.awaiting = s.awaiting, None
        cid = _pick_candidate(text, aw["candidates"])
        if cid:
            v = validate(db, shop_id, aw["extraction"], lang, db.get(Customer, cid))
            return _handle_validation(db, shop, s, v, aw["extraction"], lang)

    if s.duplicate:                                  # "already registered, use that one?"
        d, s.duplicate = s.duplicate, None
        if is_no(text):
            return _out("cancelled", say(lang, "cancelled"))
        if is_yes(text):
            return _after_registration(db, shop, s, db.get(Customer, d["customer_id"]),
                                       d["then"], lang)

    if s.pending:                                    # waiting for yes / no
        if is_no(text):
            s.pending = None
            return _out("cancelled", say(lang, "cancelled"))
        if is_yes(text):
            return _commit(db, shop, s, lang)
        s.pending = None                             # something else: treat as new command

    ex = None
    if s.followup:                                   # "What did Aryan take?"
        f = s.followup
        if is_no(text):
            s.followup = None
            return _out("saved", say(lang, "registered", name=f["name"]))
        ex = extract(db, shop_id, text, hint=FOLLOWUP_HINT)
        if ex.intent == "add_credit" and not ex.customer_ref:
            v = validate(db, shop_id, ex, lang, forced_customer=db.get(Customer, f["customer_id"]))
            if v.status == "ready":
                s.followup = None
                return _handle_validation(db, shop, s, v, ex, lang, new_customer=True)
            return _out("error", say(lang, v.code, **v.info))   # keep followup so they can retry
        s.followup = None                            # a different command: handle it normally

    if ex is None:
        ex = extract(db, shop_id, text)
    if ex.intent == "add_customer":
        return _start_registration(db, shop, s, ex, lang)
    v = validate(db, shop_id, ex, lang)
    return _handle_validation(db, shop, s, v, ex, lang)