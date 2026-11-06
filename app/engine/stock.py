"""Stock intelligence: sales speed, reorder points, smart alerts, nightly job.
Sales history = credit sales from the ledger + cash sales from sales_log."""
import math
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select

from app.db.models import ActionAudit, CashState, Item, LedgerEntry, SaleLog, Shop
from app.engine import clock
from app.voice.templates_cash import num, tc

try:
    from app.voice.templates import item_label
except Exception:  # pragma: no cover
    item_label = None

WINDOW_DAYS = 30
MIN_SPAN = 7          # never divide by fewer than 7 days (one busy day must not look like a trend)
SAFETY_DAYS = 2
DEFAULT_LEAD = 3
COVER_DAYS = 7
EXPIRY_DAYS = 7
DEAD_DAYS = 30


def label(item, lang: str) -> str:
    if item_label is not None:
        try:
            return item_label(item, lang)
        except Exception:
            pass
    return item.name


def set_cash(db, shop_id: int, cash=None, payables=None, lead_time_days=None, now=None) -> CashState:
    now = now or clock.now()
    cs = db.get(CashState, shop_id)
    if cs is None:
        cs = CashState(shop_id=shop_id, cash=None, payables=0, lead_time_days=DEFAULT_LEAD)
        db.add(cs)
    if cash is not None:
        cs.cash = max(int(cash), 0)
    if payables is not None:
        cs.payables = max(int(payables), 0)
    if lead_time_days is not None:
        cs.lead_time_days = max(int(lead_time_days), 1)
    cs.updated_at = now
    db.add(ActionAudit(shop_id=shop_id, actor="shopkeeper", tool="set_cash",
                       arguments={"cash": cs.cash, "payables": cs.payables,
                                  "lead_time_days": cs.lead_time_days},
                       rule_decision="allowed", timestamp=now))
    db.commit()
    return cs


def _name_map(items) -> dict:
    m = {}
    for it in items:
        for n in [it.name] + list(it.aliases or []):
            m[str(n).strip().lower()] = it.id
    return m


def sales_rows(db, shop_id: int, since: datetime) -> list:
    items = db.scalars(select(Item).where(Item.shop_id == shop_id)).all()
    ids = {i.id for i in items}
    names = _name_map(items)
    rows = []
    for e in db.scalars(select(LedgerEntry).where(
            LedgerEntry.shop_id == shop_id, LedgerEntry.type == "credit",
            LedgerEntry.created_at >= since)).all():
        for ln in (e.items_json or []):
            if not isinstance(ln, dict):
                continue
            iid = ln.get("item_id")
            if iid not in ids:
                iid = names.get(str(ln.get("name", "")).strip().lower())
            try:
                q = ln.get("qty")
                qty = float(q if q is not None else (ln.get("quantity") or 0))
            except (TypeError, ValueError):
                continue
            if iid and qty > 0:
                rows.append((iid, qty, e.created_at))
    for s in db.scalars(select(SaleLog).where(SaleLog.shop_id == shop_id, SaleLog.sold_at >= since)).all():
        rows.append((s.item_id, float(s.qty), s.sold_at))
    return rows


def compute_stock(db, shop_id: int, now: Optional[datetime] = None) -> list[dict]:
    now = now or clock.now()
    cs = db.get(CashState, shop_id)
    lead = cs.lead_time_days if (cs and cs.lead_time_days) else DEFAULT_LEAD
    items = db.scalars(select(Item).where(Item.shop_id == shop_id).order_by(Item.id)).all()
    rows = sales_rows(db, shop_id, now - timedelta(days=90))
    win_start = now - timedelta(days=WINDOW_DAYS)
    recent, last, first = defaultdict(float), {}, None
    for iid, qty, at in rows:
        if at >= win_start:
            recent[iid] += qty
            if first is None or at < first:
                first = at
        if iid not in last or at > last[iid]:
            last[iid] = at
    span = WINDOW_DAYS if first is None else max(MIN_SPAN, min(WINDOW_DAYS, (now - first).days + 1))

    out = []
    for it in items:
        daily = recent.get(it.id, 0.0) / span
        stock = float(it.stock_qty or 0)
        if daily > 0:
            rp = float(math.ceil(round(daily * lead + daily * SAFETY_DAYS, 6)))
        else:
            rp = float(it.reorder_level or 0)       # too little history: use the shop's default level
        days_left = stock / daily if daily > 0 else None
        is_out = stock <= 0
        low = is_out or (rp > 0 and stock <= rp)
        lts = [x for x in (last.get(it.id), it.last_sold_at) if x]
        lt = max(lts) if lts else None
        dead_days = (now - lt).days if lt else None
        dead = stock > 0 and dead_days is not None and dead_days >= DEAD_DAYS
        exp_days = (it.expiry_date - now.date()).days if it.expiry_date else None
        near = exp_days is not None and exp_days <= EXPIRY_DAYS and stock > 0
        out.append({"item": it, "item_id": it.id, "stock": stock, "daily": daily, "lead": lead,
                    "reorder_point": rp, "days_left": days_left, "out": is_out, "low": low,
                    "near_expiry": near, "expiry_days": exp_days, "dead": dead, "dead_days": dead_days})
    return out


def alerts(db, shop_id: int, now: Optional[datetime] = None, limit: int = 3, lang: Optional[str] = None) -> list[dict]:
    """One alert per item (its most urgent problem), ranked, top `limit` only (alert fatigue)."""
    now = now or clock.now()
    lang = lang or db.get(Shop, shop_id).language
    cands = []
    for s in compute_stock(db, shop_id, now):
        it = s["item"]
        name = label(it, lang)
        opts = []
        if s["out"]:
            opts.append((100.0, "out", tc(lang, "al_out", item=name)))
        elif s["low"]:
            dl = s["days_left"]
            sc = 50.0 + (min(40.0, 20.0 / max(dl, 0.5)) if dl is not None else 0.0)
            opts.append((sc, "low", tc(lang, "al_low", item=name, stock=num(s["stock"]), unit=it.unit)))
        if s["near_expiry"]:
            d = s["expiry_days"]
            opts.append((40.0 + max(0, EXPIRY_DAYS - d) * 3, "expiry",
                         tc(lang, "al_expired" if d < 0 else "al_exp", item=name, days=d)))
        if s["dead"]:
            opts.append((20.0, "dead", tc(lang, "al_dead", item=name, days=s["dead_days"])))
        if opts:
            sc, kind, text = max(opts, key=lambda o: o[0])
            cands.append({"item_id": it.id, "name": name, "kind": kind, "score": round(sc, 1), "text": text})
    cands.sort(key=lambda a: a["score"], reverse=True)
    return cands[:limit] if limit else cands


def nightly(db, shop_id: int, now: Optional[datetime] = None) -> dict:
    """Once per (demo-clock) day: save computed reorder points into Item.reorder_level."""
    now = now or clock.now()
    day = now.date().isoformat()
    recent = db.scalars(select(ActionAudit).where(
        ActionAudit.shop_id == shop_id, ActionAudit.tool == "nightly_stock"
    ).order_by(ActionAudit.id.desc()).limit(5)).all()
    if any(a.arguments.get("day") == day for a in recent):
        return {"status": "already_ran"}
    changed = []
    for s in compute_stock(db, shop_id, now):
        if s["daily"] > 0:
            it = s["item"]
            if abs((it.reorder_level or 0) - s["reorder_point"]) >= 0.01:
                changed.append({"item_id": it.id, "old": it.reorder_level, "new": s["reorder_point"]})
                it.reorder_level = s["reorder_point"]
    db.add(ActionAudit(shop_id=shop_id, actor="scheduler", tool="nightly_stock",
                       arguments={"day": day, "changed": changed}, rule_decision="allowed", timestamp=now))
    db.commit()
    return {"status": "done", "changed": len(changed)}