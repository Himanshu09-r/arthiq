"""Voice stock-in (goods received): plan -> spoken read-back -> confirmed commit.

This module owns NO inventory logic of its own. It resolves what was said into catalogue items
(item_match), converts units (units), and builds the preview. The actual write happens only after
the shopkeeper says yes, through the existing purchase service (engine.purchases.record_purchase),
which creates the Purchase + PurchaseItem rows and calls the unified movement engine
(engine.stock_movement.record_movement) for every line: STOCK_IN movement, stock update, audit
row and idempotency, all in ONE database transaction.

plan_stock_in() is read-only. commit_stock_in() is the only function that writes.
"""
import hashlib
from dataclasses import dataclass, field
from typing import Optional
from types import SimpleNamespace

from rapidfuzz import fuzz
from sqlalchemy import select

from app.db.models import Item, Supplier
from app.engine import item_match, units
from app.engine.products import register_product, ProductError
from app.engine.purchases import PurchaseError, record_purchase
from app.engine.stock_movement import MovementError
from app.voice.templates import item_label
from app.voice.templates_stock import n as num, ts, unit_say

MAX_QTY = 100000


class StockInError(Exception):
    def __init__(self, code: str, **info):
        super().__init__(code)
        self.code = code
        self.info = info


@dataclass
class StockPlan:
    status: str                                  # ready | ask | error
    lines: list = field(default_factory=list)    # plain dicts (JSON-safe, kept in the session)
    supplier: Optional[dict] = None              # {"name": str, "id": int|None}
    code: Optional[str] = None                   # template key for ask / error
    info: dict = field(default_factory=dict)
    ask: Optional[dict] = None                   # {"kind": which|unknown, "idx": int, "candidates": [...]}


# ------------------------------------------------------------------ helpers
def find_supplier(db, shop_id: int, name: Optional[str]) -> Optional[dict]:
    if not name or not name.strip():
        return None
    q = name.strip().casefold()
    best, found = 0, None
    for s in db.scalars(select(Supplier).where(Supplier.shop_id == shop_id, Supplier.status == "active")).all():
        sc = fuzz.ratio(q, s.name.casefold())
        if sc > best:
            best, found = sc, s
    if found is not None and best >= 88:
        return {"name": found.name, "id": found.id}
    return {"name": name.strip(), "id": None}       # will be created on commit, after confirmation


def _price_per_item_unit(price, spoken_qty, item_qty) -> Optional[int]:
    """Purchase price is spoken per spoken-unit. Re-express per item unit (whole rupees)."""
    if price is None or price < 0:
        return None
    if not item_qty:
        return int(round(price))
    return int(round(price * spoken_qty / item_qty))


def _ask_options(res: item_match.Resolution, lang: str):
    return [{"item_id": c.item.id, "label": item_label(c.item, lang)} for c in (res.options or [])]


# ------------------------------------------------------------------ plan (read-only)
def plan_stock_in(db, shop_id: int, spoken: list[dict], supplier_name: Optional[str], lang: str,
                  choices: Optional[dict] = None) -> StockPlan:
    """spoken = [{"name","qty","unit","price"}]; choices = {"<idx>": {"item_id": 3} | {"new": {...}}}"""
    choices = choices or {}
    if not spoken:
        return StockPlan("error", code="st_ask_items")
    merged: dict = {}
    order: list = []
    for idx, sp in enumerate(spoken):
        name = str(sp.get("name") or "").strip()
        try:
            qty = float(sp.get("qty") or 0)
        except (TypeError, ValueError):
            qty = 0.0
        if qty <= 0 or qty > MAX_QTY or not name:
            return StockPlan("error", code="st_err_qty", info={"name": name or "?"})
        unit = sp.get("unit")
        if unit and not units.canon_unit(unit):
            return StockPlan("error", code="st_err_unit_unknown", info={"unit": unit})
        spoken_unit = units.canon_unit(unit) if unit else None
        choice = choices.get(str(idx)) or {}

        item = None
        new_product = None
        if choice.get("item_id"):
            item = db.get(Item, choice["item_id"])
            if not item or item.shop_id != shop_id:
                return StockPlan("error", code="err_generic")
        elif choice.get("new"):
            new_product = dict(choice["new"])
        else:
            res = item_match.resolve(db, shop_id, name)
            if res.status == "match":
                item = res.item
            elif res.status in ("ambiguous", "maybe"):
                opts = _ask_options(res, lang)
                if res.status == "maybe" and len(opts) == 1:
                    return StockPlan("ask", code="st_ask_maybe",
                                     info={"name": name, "option": opts[0]["label"]},
                                     ask={"kind": "which", "idx": idx, "name": name, "candidates": opts,
                                          "single": True})
                return StockPlan("ask", code="st_ask_which",
                                 info={"name": name, "options": " / ".join(o["label"] for o in opts)},
                                 ask={"kind": "which", "idx": idx, "name": name, "candidates": opts})
            else:
                return StockPlan("ask", code="st_ask_unknown", info={"name": name},
                                 ask={"kind": "unknown", "idx": idx, "name": name, "candidates": [],
                                      "spoken_unit": spoken_unit})

        if new_product is not None:
            n_unit = new_product["unit"]
            conv = units.convert(qty, spoken_unit, SimpleNamespace(unit=n_unit))
            if not conv.ok:
                return StockPlan("error", code="st_err_unit", info={
                    "item": new_product["name"], "unit": unit_say(lang, n_unit),
                    "spoken": unit_say(lang, spoken_unit or "")})
            line = {"idx": idx, "item_id": None, "name": new_product["name"], "label": new_product["name"],
                    "unit": n_unit, "qty": conv.qty, "prev": 0.0, "new": conv.qty, "approx": False,
                    "spoken_qty": qty, "spoken_unit": spoken_unit,
                    "price": _price_per_item_unit(sp.get("price"), qty, conv.qty),
                    "new_product": new_product, "sell_price": new_product["price"]}
            key = ("new", new_product["name"].casefold())
        else:
            conv = units.convert(qty, spoken_unit, item)
            if not conv.ok:
                if conv.reason == "unknown_unit":
                    return StockPlan("error", code="st_err_unit_unknown", info={"unit": unit})
                return StockPlan("error", code="st_err_unit", info={
                    "item": item_label(item, lang), "unit": unit_say(lang, item.unit),
                    "spoken": unit_say(lang, spoken_unit or "")})
            prev = float(item.stock_qty or 0)
            line = {"idx": idx, "item_id": item.id, "name": item.name, "label": item_label(item, lang),
                    "unit": item.unit, "qty": conv.qty, "prev": prev, "new": round(prev + conv.qty, 4),
                    "approx": conv.approximate, "spoken_qty": qty, "spoken_unit": spoken_unit,
                    "price": _price_per_item_unit(sp.get("price"), qty, conv.qty),
                    "new_product": None, "sell_price": None}
            key = ("item", item.id)

        if key in merged:                               # same product twice in one sentence: add up
            m = merged[key]
            m["qty"] = round(m["qty"] + line["qty"], 4)
            m["new"] = round(m["prev"] + m["qty"], 4)
            m["approx"] = m["approx"] or line["approx"]
            if m["price"] is None:
                m["price"] = line["price"]
        else:
            merged[key] = line
            order.append(key)

    sup = find_supplier(db, shop_id, supplier_name)
    return StockPlan("ready", lines=[merged[k] for k in order], supplier=sup)


# ------------------------------------------------------------------ read-back text
def readback(lang: str, plan: StockPlan) -> str:
    """The sentence the shopkeeper hears before anything is saved."""
    lines = plan.lines

    def extras(ln):
        out = ""
        if ln.get("approx"):
            out += ts(lang, "st_x_approx", spoken=f"{num(ln['spoken_qty'])} {unit_say(lang, ln['spoken_unit'])}",
                      unit=unit_say(lang, ln["unit"]))
        if ln.get("price") is not None:
            out += ts(lang, "st_x_price", price=ln["price"], unit=unit_say(lang, ln["unit"]))
        if ln.get("new_product"):
            out += ts(lang, "st_x_new", price=ln["sell_price"], unit=unit_say(lang, ln["unit"]))
        return out

    sup = ts(lang, "st_x_supplier", supplier=plan.supplier["name"]) if plan.supplier else ""
    if len(lines) == 1:
        ln = lines[0]
        return ts(lang, "st_one", qty=num(ln["qty"]), unit=unit_say(lang, ln["unit"]), item=ln["label"],
                  prev=num(ln["prev"]), new=num(ln["new"]), extra=extras(ln) + sup)
    parts = [ts(lang, "st_line", qty=num(l["qty"]), unit=unit_say(lang, l["unit"]), item=l["label"],
                prev=num(l["prev"]), new=num(l["new"])) + extras(l) for l in lines]
    return ts(lang, "st_many", n=len(lines), lines="; ".join(parts), extra=sup)


def saved_text(lang: str, result: dict) -> str:
    rows = result["lines"]
    if len(rows) == 1:
        r = rows[0]
        return ts(lang, "st_saved_one", item=r["label"], new=num(r["new_stock"]), unit=unit_say(lang, r["unit"]))
    parts = [ts(lang, "st_sline", item=r["label"], new=num(r["new_stock"]), unit=unit_say(lang, r["unit"]))
             for r in rows]
    return ts(lang, "st_saved_many", n=len(rows), lines="; ".join(parts))


# ------------------------------------------------------------------ commit (the only writer)
def commit_stock_in(db, shop_id: int, lines: list[dict], supplier: Optional[dict], request_id: str,
                    lang: str = "hi-IN", note: Optional[str] = None) -> dict:
    """Apply a CONFIRMED stock-in. Idempotent on request_id (a second call changes nothing)."""
    if not lines:
        raise StockInError("no_items")
    idem = "voice_in_" + hashlib.sha1(f"{shop_id}:{request_id}".encode()).hexdigest()[:40]
    try:
        supplier_id = None
        if supplier:
            supplier_id = supplier.get("id")
            if supplier_id is None:
                existing = find_supplier(db, shop_id, supplier["name"])
                supplier_id = existing["id"] if existing and existing["id"] else None
            if supplier_id is None:
                from datetime import datetime
                sup = Supplier(shop_id=shop_id, name=supplier["name"], status="active",
                               created_at=datetime.now(), updated_at=datetime.now())
                db.add(sup)
                db.flush()
                supplier_id = sup.id

        purchase_lines, item_ids = [], []
        for ln in lines:
            item_id = ln.get("item_id")
            if item_id is None and ln.get("new_product"):
                np_ = ln["new_product"]
                item = register_product(db, shop_id, np_["name"], np_["unit"], int(round(np_["price"])),
                                        cost_price=int(ln.get("price") or 0), aliases=[np_["name"].lower()],
                                        allow_existing=True, commit=False)
                item_id = item.id
            item_ids.append(item_id)
            purchase_lines.append({"item_id": item_id, "quantity": ln["qty"], "unit": ln["unit"],
                                   "purchase_price": ln.get("price")})
        res = record_purchase(db, shop_id, purchase_lines, supplier_id=supplier_id, idempotency_key=idem,
                              notes=note or "voice stock-in")
    except (PurchaseError, MovementError, ProductError) as e:
        db.rollback()
        raise StockInError(getattr(e, "code", "failed"), message=str(e))
    except Exception:
        db.rollback()
        raise

    rows = []
    for ln, item_id in zip(lines, item_ids):
        it = db.get(Item, item_id)
        rows.append({"item_id": item_id, "label": item_label(it, lang), "unit": it.unit,
                     "added": ln["qty"], "new_stock": float(it.stock_qty or 0)})
    return {"purchase_id": res["purchase_id"], "replay": res.get("replay", False),
            "total_amount": res["total_amount"], "lines": rows}