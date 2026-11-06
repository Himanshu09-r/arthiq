import uuid
import json, time, threading
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
from app.db.models import Shop, Customer, Item
from app.engine import confirmation as C
from app.engine.confirmation import classify
from app.agent import intents, stock_flow
from app.engine.daily_intelligence import compute_daily_summary
from app.languages import normalize_language

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
    stock_ask: Optional[dict] = None   # stock-in clarification (product / quantity / new product)


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
        if p["action"] == "stock_in":
            return stock_flow.commit(db, shop, s, p, lang)
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


# ---------- daily summary (read-only) ----------
def _daily_summary(db, shop, s, lang):
    """Today's SQL-backed business report. This function never writes to the database."""
    data = compute_daily_summary(db, shop.id, lang=lang)
    reply = data["spoken_text"]
    # Summaries remain read-only; do not ask for or trigger reminder approval here.
    result = _out("summary", reply)
    result["summary"] = {
        "sales": data.get("cash_sales", 0) + data.get("credit_sales", 0),
        "collected": data.get("money_collected", 0),
        "cash_sales": data.get("cash_sales", 0),
        "credit_sales": data.get("credit_sales", data.get("credit_given_today", 0)),
        "outstanding_total": data.get("outstanding_total", 0),
        "overdue_count": data.get("overdue_count", 0),
        "overdue_amount": data.get("overdue_amount", 0),
        "stock_in_lines": data.get("stock_in_lines", 0),
        "stock_in_amount": data.get("stock_in_amount", 0),
        "low_stock_count": data.get("low_stock_count", 0),
        "out_of_stock_count": data.get("out_of_stock_count", 0),
    }
    return result


# ---------- main entry ----------
def _handle_legacy(db, shop_id: int, text: str) -> dict:
    shop = db.get(Shop, shop_id)
    lang = normalize_language(shop.language)
    s = _session(shop_id)

    if intents.is_daily_summary(text):
        return _daily_summary(db, shop, s, lang)

    if s.stock_ask:
        answer = stock_flow.answer(db, shop, s, text, lang)
        if answer is not None:
            return answer

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
        stock = intents.parse_stock_in(text)
        if stock is not None:
            return stock_flow.start(db, shop, s, stock["items"], stock.get("supplier"), lang,
                                    needs_items=stock.get("needs_items", False))
        ex = extract(db, shop_id, text)
    if ex.intent == "stock_in":
        return stock_flow.start_from_extraction(db, shop, s, ex, lang)
    if ex.intent == "daily_summary":
        return _daily_summary(db, shop, s, lang)
    if ex.intent == "add_customer":
        return _start_registration(db, shop, s, ex, lang)
    v = validate(db, shop_id, ex, lang)
    return _handle_validation(db, shop, s, v, ex, lang)


# ===================== Spoken confirmation engine =====================
CORRECTION_HINT = (
    "The shopkeeper was asked to confirm a command and has now replied with a correction or "
    "something else. PREVIOUS COMMAND: {prev}. Return the FULL corrected command as the JSON. "
    "Copy every field the shopkeeper did not change from the previous command. 'no, 300' or "
    "'500 nahi, 300' changes only the amount. If the shopkeeper clearly states a completely "
    "different command, return that command instead. If the reply is not a command or a "
    "correction, intent is 'other'.")

_LOCKS: dict[int, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(shop_id):
    with _LOCKS_GUARD:
        return _LOCKS.setdefault(shop_id, threading.Lock())


def _prev_json(db, p) -> dict:
    """The pending command as extraction-style JSON, so the LLM can apply a correction to it."""
    if p["action"] == "stock_in":
        return stock_flow.prev_json(p)
    if p["action"] == "register_customer":
        d = {"intent": "add_customer", "customer_ref": p["name"], "locality": p.get("locality"),
             "phone": p.get("phone"), "language": p.get("language"),
             "credit_limit": p.get("credit_limit")}
        t = p.get("then")
        if t:
            d["items"] = [i.model_dump() for i in (t.items or [])]
            d["amount"] = t.amount
        return d
    if p["action"] == "record_payment":
        return {"intent": "record_payment", "customer_ref": p["name"], "amount": p["amount"]}
    d = {"intent": "add_credit", "customer_ref": p["name"]}
    if p["action"] == "add_credit_items":
        d["items"] = [{"name": db.get(Item, l["item_id"]).name, "qty": l["qty"], "unit": l["unit"]}
                      for l in p["lines"]]
    else:
        d["amount"] = p["total"]
    return d


def _correct(db, shop, s, text, lang, p):
    """Apply a deterministic stock-in correction first, then use the existing LLM correction path."""
    if p.get("action") == "stock_in":
        r = stock_flow.correct(db, shop, s, text, lang, p)
        if r is not None:
            if r["state"] == "confirm" and s.pending:
                s.pending["_readback"] = r["reply"]
                r["reply"] = say(lang, "corrected") + " " + r["reply"]
            return r

    prev = json.dumps(_prev_json(db, p), ensure_ascii=False)
    ex = extract(db, shop.id, text, hint=CORRECTION_HINT.format(prev=prev))
    if ex.intent == "other":
        return None
    s.pending = None
    if ex.intent == "add_customer":
        r = _start_registration(db, shop, s, ex, lang)
    elif ex.intent == "stock_in":
        r = stock_flow.start_from_extraction(db, shop, s, ex, lang)
    else:
        forced = None
        if not ex.customer_ref and p.get("customer_id"):
            forced = db.get(Customer, p["customer_id"])
        v = validate(db, shop.id, ex, lang, forced_customer=forced)
        r = _handle_validation(db, shop, s, v, ex, lang, new_customer=p.get("new_customer", False))
    if r["state"] == "confirm" and s.pending:
        s.pending["_readback"] = r["reply"]
        r["reply"] = say(lang, "corrected") + " " + r["reply"]
    return r


def _confirm_turn(db, shop, s, text, lang):
    p = s.pending
    rep = classify(text, lang)
    if rep.kind == "yes":
        r = _commit(db, shop, s, lang)               # idempotent: same request_id
        if r["state"] == "saved":
            s.last_commit = {"t": time.monotonic(), "rid": p["request_id"]}
        return r
    if rep.kind == "no":
        s.pending = None
        return _out("cancelled", say(lang, "cancelled"))
    if rep.kind in ("correction", "other"):
        r = _correct(db, shop, s, text, lang, p)
        if r is not None:
            return r
    # empty / unclear / not a command: ask again, keep the same pending item
    p["_n"] = p.get("_n", 0) + 1
    if p["_n"] > 2:
        s.pending = None
        return _out("cancelled", say(lang, "cancelled"))
    p["_t"] = time.monotonic()
    return _out("confirm", say(lang, "reprompt") + " " + p.get("_readback", ""))


def _decorate(s, r):
    r["listen"] = bool(s.pending or s.awaiting or s.duplicate or getattr(s, "followup", None)
                       or getattr(s, "stock_ask", None))
    if s.pending:
        r["confirmation_id"] = s.pending.get("request_id")
        r["expires_in"] = C.TTL
    return r


def handle(db, shop_id: int, text: str) -> dict:
    with _lock_for(shop_id):                         # button + voice at once = one at a time
        shop = db.get(Shop, shop_id)
        lang = normalize_language(shop.language)
        s = _session(shop_id)
        expired = C.expire_stale(s)
        waiting = bool(s.awaiting or s.duplicate or getattr(s, "followup", None)
                       or getattr(s, "stock_ask", None))

        if intents.is_daily_summary(text):             # report request is read-only; keep pending confirmations intact
            r = _daily_summary(db, shop, s, lang)
        elif s.pending:
            r = _confirm_turn(db, shop, s, text, lang)
        else:
            rep = classify(text, lang)
            lc = getattr(s, "last_commit", None)
            if expired is not None and rep.kind in ("yes", "no", "empty"):
                r = _out("cancelled", say(lang, "expired"))
            elif not waiting and rep.kind == "yes" and lc and time.monotonic() - lc["t"] < 20:
                r = _out("saved", say(lang, "already_saved"))
            elif not waiting and rep.kind in ("yes", "no"):
                r = _out("error", say(lang, "nothing_pending"))
            else:
                r = _handle_legacy(db, shop_id, text)

        C.stamp(s)
        if s.pending and r["state"] == "confirm":
            s.pending.setdefault("_readback", r["reply"])
        return _decorate(s, r)