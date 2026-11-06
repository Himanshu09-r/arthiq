"""Conversation flow for voice stock-in, used by agent.pipeline.

States kept on the session (pipeline.Session):
  s.pending    {"action": "stock_in", ...}   waiting for yes / no  (nothing is written yet)
  s.stock_ask  {...}                         waiting for a clarification:
       kind "items"    - "which item and how much arrived?"
       kind "which"    - ambiguous / near-miss product ("which oil?")
       kind "unknown"  - product not in the catalogue ("which product, or is it new?")
       kind "newprice" - new product, waiting for its selling price

Nothing here writes to the database except commit(), which runs only after the spoken
confirmation, and which delegates to engine.stock_in.commit_stock_in (-> purchases / movement engine).
"""
import uuid
from typing import Optional

from rapidfuzz import fuzz

from app.agent import intents
from app.engine import item_match
from app.engine import stock_in as SI
from app.engine.confirmation import classify
from app.voice.templates import say
from app.voice.templates_stock import ts

_ORDINALS = {"pehla": 1, "pehle": 1, "pahla": 1, "first": 1, "1": 1, "ek": 1, "पहला": 1, "पहले": 1,
             "doosra": 2, "dusra": 2, "dusre": 2, "second": 2, "2": 2, "do": 2, "दूसरा": 2, "दूसरे": 2,
             "teesra": 3, "third": 3, "3": 3, "teen": 3, "तीसरा": 3}


def _out(state, reply):
    return {"state": state, "reply": reply}


# ------------------------------------------------------------------ build the pending confirmation
def _ready(db, shop, s, plan: SI.StockPlan, spoken, supplier_name, choices, lang):
    s.stock_ask = None
    s.pending = {"action": "stock_in", "lines": plan.lines, "supplier": plan.supplier,
                 "spoken": spoken, "supplier_name": supplier_name, "choices": choices,
                 "request_id": uuid.uuid4().hex}
    return _out("confirm", SI.readback(lang, plan))


def _run_plan(db, shop, s, spoken, supplier_name, choices, lang):
    plan = SI.plan_stock_in(db, shop.id, spoken, supplier_name, lang, choices)
    if plan.status == "ready":
        return _ready(db, shop, s, plan, spoken, supplier_name, choices, lang)
    if plan.status == "ask":
        if plan.ask and plan.ask["kind"] == "items":
            pass
        s.stock_ask = {**plan.ask, "spoken": spoken, "supplier_name": supplier_name, "choices": choices,
                       "step": plan.ask["kind"]}
        return _out("ask", ts(lang, plan.code, **plan.info))
    # error
    s.stock_ask = None
    if plan.code == "st_ask_items":
        s.stock_ask = {"kind": "items", "step": "items", "spoken": [], "supplier_name": supplier_name,
                       "choices": {}, "candidates": []}
        return _out("ask", ts(lang, "st_ask_items"))
    if plan.code in ("err_generic",):
        return _out("error", say(lang, plan.code))
    return _out("error", ts(lang, plan.code, **plan.info))


def start(db, shop, s, items: list[dict], supplier_name: Optional[str], lang: str, needs_items=False):
    """New stock-in statement. `items` = [{"name","qty","unit","price"}]."""
    s.pending = None
    if not items:
        s.stock_ask = {"kind": "items", "step": "items", "spoken": [], "supplier_name": supplier_name,
                       "choices": {}, "candidates": []}
        return _out("ask", ts(lang, "st_ask_items"))
    return _run_plan(db, shop, s, items, supplier_name, {}, lang)


def start_from_extraction(db, shop, s, ex, lang):
    items = [{"name": i.name, "qty": i.qty, "unit": i.unit, "price": i.price} for i in (ex.items or [])]
    return start(db, shop, s, items, ex.supplier, lang)


# ------------------------------------------------------------------ answers to a clarification
def _pick_candidate(db, shop, text, ask, lang):
    """Which of the offered products did the shopkeeper mean? -> item_id or None."""
    cands = ask["candidates"]
    toks = item_match.canon(text).split()
    for t in toks:
        k = _ORDINALS.get(t)
        if k and k <= len(cands):
            return cands[k - 1]["item_id"]
    q = item_match.canon(text)
    scored = []
    for c in cands:
        lab = item_match.canon(c["label"])
        sc = max(fuzz.partial_ratio(q, lab), fuzz.token_set_ratio(q, lab))
        scored.append((sc, c["item_id"]))
    scored.sort(reverse=True)
    if scored and scored[0][0] >= 85 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 8):
        return scored[0][1]
    res = item_match.resolve(db, shop.id, text)          # they named some other catalogue product
    if res.status == "match":
        return res.item.id
    return None


def _cancel(s, lang):
    s.stock_ask = None
    return _out("cancelled", say(lang, "cancelled"))


def answer(db, shop, s, text: str, lang: str) -> Optional[dict]:
    """Handle the reply to a stock clarification. None = unrelated; caller treats it as a new command."""
    ask, s.stock_ask = s.stock_ask, None
    kind = ask["kind"]
    spoken, sup, choices = ask["spoken"], ask["supplier_name"], dict(ask["choices"])

    if kind == "items":
        rep = classify(text, lang)
        if rep.kind == "no":
            return _out("cancelled", say(lang, "cancelled"))
        parsed = intents.parse_stock_items(text)
        if not parsed:
            s.stock_ask = ask
            return None
        return _run_plan(db, shop, s, parsed["items"], parsed["supplier"] or sup, {}, lang)

    idx = str(ask["idx"])
    rep = classify(text, lang)

    if kind == "which":
        if ask.get("single"):
            if rep.kind == "yes":
                choices[idx] = {"item_id": ask["candidates"][0]["item_id"]}
                return _run_plan(db, shop, s, spoken, sup, choices, lang)
            if rep.kind == "no":                         # not that one: treat as a product we do not have
                s.stock_ask = {**ask, "kind": "unknown", "step": "unknown", "single": False, "candidates": []}
                return _out("ask", ts(lang, "st_ask_unknown", name=ask["name"]))
        if rep.kind == "no" and not rep.content:
            return _cancel(s, lang)
        item_id = _pick_candidate(db, shop, text, ask, lang)
        if item_id is None:
            s.stock_ask = ask
            return None
        choices[idx] = {"item_id": item_id}
        return _run_plan(db, shop, s, spoken, sup, choices, lang)

    if kind == "unknown":
        np_ = intents.parse_new_product(text)
        if np_["cancel"]:
            return _cancel(s, lang)
        if not np_["is_new"]:                            # maybe they named a product that exists
            res = item_match.resolve(db, shop.id, text)
            if res.status == "match":
                choices[idx] = {"item_id": res.item.id}
                return _run_plan(db, shop, s, spoken, sup, choices, lang)
            if rep.kind == "no":
                return _cancel(s, lang)
            s.stock_ask = ask
            return None
        unit = np_["unit"] or ask.get("spoken_unit") or ask.get("new_unit")
        spoken_price = intents.parse_single_quantity(text)
        price = np_["price"] if np_["price"] is not None else (spoken_price[0] if spoken_price else None)
        if price is None or unit is None:
            s.stock_ask = {**ask, "kind": "newprice", "step": "newprice", "new_unit": unit}
            return _out("ask", ts(lang, "st_ask_newprice", name=ask["name"]))
        return _new_product(db, shop, s, ask, spoken, sup, choices, idx, unit, price, lang)

    if kind == "newprice":
        np_ = intents.parse_new_product(text)
        if np_["cancel"]:
            return _cancel(s, lang)
        parsed = intents.parse_single_quantity(text)     # "30" / "30 rupaye" / "packet 30"
        price = np_["price"] if np_["price"] is not None else (parsed[0] if parsed else None)
        unit = np_["unit"] or ask.get("new_unit") or ask.get("spoken_unit")
        if price is None or unit is None:
            s.stock_ask = ask
            return _out("ask", ts(lang, "st_ask_newprice", name=ask["name"]))
        return _new_product(db, shop, s, ask, spoken, sup, choices, idx, unit, price, lang)
    return None


def _new_product(db, shop, s, ask, spoken, sup, choices, idx, unit, price, lang):
    if price <= 0 or price > 1_000_000:                  # never invent or accept a nonsense price
        s.stock_ask = {**ask, "kind": "newprice", "step": "newprice", "new_unit": unit}
        return _out("ask", ts(lang, "st_ask_newprice", name=ask["name"]))
    choices[idx] = {"new": {"name": ask["name"].strip().title(), "unit": unit, "price": int(round(price))}}
    return _run_plan(db, shop, s, spoken, sup, choices, lang)


# ------------------------------------------------------------------ correction of a pending read-back
def correct(db, shop, s, text: str, lang: str, p: dict) -> Optional[dict]:
    """Deterministic corrections for a pending stock-in. None = let the LLM try."""
    full = intents.parse_stock_in(text)
    if full and full["items"]:                           # a whole new statement replaces the old one
        s.pending = None
        return start(db, shop, s, full["items"], full["supplier"], lang)
    one = intents.parse_single_quantity(text)
    spoken = [dict(x) for x in p.get("spoken", [])]
    if one and len(spoken) == 1:                         # "nahi, 12 kilo" -> only the quantity changes
        spoken[0]["qty"] = one[0]
        if one[1]:
            spoken[0]["unit"] = one[1]
        s.pending = None
        return _run_plan(db, shop, s, spoken, p.get("supplier_name"), p.get("choices", {}), lang)
    return None


def prev_json(p: dict) -> dict:
    return {"intent": "stock_in", "supplier": p.get("supplier_name"),
            "items": [{"name": x.get("name"), "qty": x.get("qty"), "unit": x.get("unit"),
                       "price": x.get("price")} for x in p.get("spoken", [])]}


# ------------------------------------------------------------------ confirmed commit
def commit(db, shop, s, p: dict, lang: str) -> dict:
    try:
        r = SI.commit_stock_in(db, shop.id, p["lines"], p.get("supplier"), p["request_id"], lang)
    except SI.StockInError as e:
        return _out("error", ts(lang, "st_failed"))
    return _out("saved", SI.saved_text(lang, r))