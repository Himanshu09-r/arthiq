"""Cash Guardian: rule-based. Dues are NOT cash until paid.
urgency = sales speed x margin / days of stock left. Greedy fill under the cash budget."""
import math
from collections import defaultdict
from datetime import datetime
from typing import Optional

from sqlalchemy import select

from app.db.models import CashState, Customer, LedgerEntry, Shop
from app.engine import clock
from app.engine.ladder import outstanding
from app.engine.stock import COVER_DAYS, SAFETY_DAYS, compute_stock, label
from app.tools.ledger_tools import get_balance
from app.voice.templates_cash import tc


def receivable_total(db, shop_id: int) -> int:
    total = 0
    for c in db.scalars(select(Customer).where(Customer.shop_id == shop_id)).all():
        total += max(get_balance(db, c.id), 0)
    return total


def collection_priorities(db, shop_id: int, now: Optional[datetime] = None, n: int = 3) -> list[dict]:
    """Who to chase first: most overdue money, then biggest balance. Disputed customers are skipped."""
    now = now or clock.now()
    today = now.date()
    by_cust = defaultdict(list)
    for e in db.scalars(select(LedgerEntry).where(
            LedgerEntry.shop_id == shop_id, LedgerEntry.type == "credit",
            LedgerEntry.status.in_(["OPEN", "PARTIAL", "DISPUTED"]))).all():
        by_cust[e.customer_id].append(e)
    out = []
    for c in db.scalars(select(Customer).where(Customer.shop_id == shop_id).order_by(Customer.id)).all():
        bal = get_balance(db, c.id)
        if bal <= 0:
            continue
        entries = by_cust.get(c.id, [])
        if any(e.status == "DISPUTED" for e in entries):
            continue
        overdue = sum(outstanding(e) for e in entries
                      if e.status in ("OPEN", "PARTIAL") and e.due_date and e.due_date < today)
        out.append({"customer_id": c.id, "name": c.name, "balance": bal, "overdue": overdue})
    out.sort(key=lambda r: (r["overdue"], r["balance"]), reverse=True)
    return out[:n]


def _plan_items(db, shop_id: int, now) -> list[dict]:
    out = []
    for s in compute_stock(db, shop_id, now):
        if not s["low"]:
            continue
        it, daily = s["item"], s["daily"]
        cover = max(COVER_DAYS, s["lead"] + SAFETY_DAYS + 2)
        if daily > 0:
            qty = math.ceil(round(daily * cover - s["stock"], 6))
        else:
            qty = math.ceil((it.reorder_level or 5) * 2 - s["stock"])
        qty = max(int(qty), 1)
        known = bool(it.cost_price)
        unit_cost = it.cost_price if known else max(1, round(it.price * 0.8))
        margin = max(it.price - unit_cost, 1)
        dl = s["days_left"] if s["days_left"] is not None else 5.0
        urgency = (daily if daily > 0 else 0.1) * margin / max(dl, 0.5)
        out.append({"item": it, "item_id": it.id, "qty": qty, "unit": it.unit, "unit_cost": unit_cost,
                    "known_price": known, "cost": qty * unit_cost, "urgency": round(urgency, 2)})
    out.sort(key=lambda r: r["urgency"], reverse=True)
    return out


def _pub(p: dict, lang: str) -> dict:
    return {"item_id": p["item_id"], "name": label(p["item"], lang), "qty": p["qty"], "unit": p["unit"],
            "unit_cost": p["unit_cost"], "known_price": p["known_price"], "cost": p["cost"],
            "urgency": p["urgency"]}


def cash_guardian(db, shop_id: int, now: Optional[datetime] = None, lang: Optional[str] = None) -> dict:
    now = now or clock.now()
    shop = db.get(Shop, shop_id)
    lang = lang or shop.language
    cs = db.get(CashState, shop_id)
    if cs is None or cs.cash is None:
        return {"need_cash": True, "text": tc(lang, "cg_ask")}

    plan = _plan_items(db, shop_id, now)
    budget = max(cs.cash - (cs.payables or 0), 0)      # receivables are never added to cash
    rem, buy, skipped = budget, [], []
    for p in plan:                                      # greedy fill, most urgent first
        if p["cost"] <= rem:
            buy.append(p)
            rem -= p["cost"]
        else:
            skipped.append(p)
    need = sum(p["cost"] for p in plan)
    spend = sum(p["cost"] for p in buy)
    prios = collection_priorities(db, shop_id, now, 3)
    recv = receivable_total(db, shop_id)

    whatif = None
    if skipped and prios[:2]:
        extra = sum(p["balance"] for p in prios[:2])
        rem2, fits = rem + extra, []
        for p in skipped:
            if p["cost"] <= rem2:
                fits.append(p["item_id"])
                rem2 -= p["cost"]
        if fits:
            whatif = {"names": [p["name"] for p in prios[:2]], "amount": extra, "items": fits}

    pub_buy = [_pub(p, lang) for p in buy]
    parts = []
    if not plan:
        parts.append(tc(lang, "cg_none", cash=cs.cash))
    elif not skipped:
        parts.append(tc(lang, "cg_fit", cash=cs.cash, need=need))
    elif buy:
        parts.append(tc(lang, "cg_part", cash=cs.cash, need=need, spend=spend,
                        items=", ".join(b["name"] for b in pub_buy[:4])))
    else:
        parts.append(tc(lang, "cg_zero", cash=cs.cash, need=need))
    if prios and recv > 0:
        parts.append(tc(lang, "cg_collect", recv=recv,
                        names=tc(lang, "and").join(p["name"] for p in prios[:2])))
    if whatif:
        parts.append(tc(lang, "cg_whatif", names=tc(lang, "and").join(whatif["names"])))

    return {"need_cash": False, "cash": cs.cash, "payables": cs.payables or 0, "budget": budget,
            "receivable": recv, "need": need, "spend": spend,
            "buy": pub_buy, "skipped": [_pub(p, lang) for p in skipped],
            "collect": prios, "whatif": whatif, "text": " ".join(parts)}