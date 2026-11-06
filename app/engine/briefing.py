"""Daily voice briefing. Numbers come from SQL and are placed by code.
The LLM may only smooth the wording; if it changes a number or drops a name, the template text is used."""
import json
import re
from datetime import datetime, time, timedelta
from typing import Optional

from sqlalchemy import select

from app.agent.llm import chat_json
from app.db.models import LedgerEntry, SaleLog, Shop
from app.engine import clock
from app.engine.cash_guardian import collection_priorities
from app.engine.ladder import outstanding
from app.engine.stock import alerts
from app.voice.templates_cash import tc
from app.voice.templates_collect import LANG_NAMES

_D = str.maketrans("०१२३४५६७८९૦૧૨૩૪૫૬૭૮૯", "01234567890123456789")


def gather(db, shop_id: int, now: datetime, lang: str) -> dict:
    start = datetime.combine(now.date(), time.min)
    end = start + timedelta(days=1)
    credit_today = sum(e.amount for e in db.scalars(select(LedgerEntry).where(
        LedgerEntry.shop_id == shop_id, LedgerEntry.type == "credit",
        LedgerEntry.created_at >= start, LedgerEntry.created_at < end)).all())
    cash_today = sum(s.amount for s in db.scalars(select(SaleLog).where(
        SaleLog.shop_id == shop_id, SaleLog.sold_at >= start, SaleLog.sold_at < end)).all())
    collected = sum(e.amount for e in db.scalars(select(LedgerEntry).where(
        LedgerEntry.shop_id == shop_id, LedgerEntry.type == "payment",
        LedgerEntry.created_at >= start, LedgerEntry.created_at < end)).all())
    over = [e for e in db.scalars(select(LedgerEntry).where(
        LedgerEntry.shop_id == shop_id, LedgerEntry.type == "credit",
        LedgerEntry.status.in_(["OPEN", "PARTIAL"]),
        LedgerEntry.due_date.is_not(None), LedgerEntry.due_date < now.date())).all()
        if outstanding(e) > 0]
    low = [a for a in alerts(db, shop_id, now, limit=5, lang=lang) if a["kind"] in ("out", "low")]
    tip = None
    if low:
        tip = ("buy", low[0]["name"])
    else:
        pr = collection_priorities(db, shop_id, now, 1)
        if pr:
            tip = ("collect", pr[0]["name"])
    return {"sales": int(credit_today + cash_today), "collected": int(collected),
            "overdue_count": len({e.customer_id for e in over}),
            "overdue_amount": int(sum(outstanding(e) for e in over)),
            "low_names": [a["name"] for a in low[:2]], "tip": tip}


def build_text(lang: str, shop_name: str, d: dict) -> str:
    parts = [tc(lang, "br_head", shop=shop_name)]
    parts.append(tc(lang, "br_sales", sales=d["sales"]) if d["sales"] > 0 else tc(lang, "br_nosales"))
    if d["collected"] > 0:
        parts.append(tc(lang, "br_collected", amount=d["collected"]))
    if d["overdue_count"] > 0:
        parts.append(tc(lang, "br_overdue", count=d["overdue_count"], amount=d["overdue_amount"]))
    else:
        parts.append(tc(lang, "br_nooverdue"))
    if d["low_names"]:
        parts.append(tc(lang, "br_stock", names=tc(lang, "and").join(d["low_names"])))
    else:
        parts.append(tc(lang, "br_stockok"))
    if d["tip"]:
        parts.append(tc(lang, "br_tip_buy" if d["tip"][0] == "buy" else "br_tip_collect", name=d["tip"][1]))
    return " ".join(parts)


def _nums(t: str) -> list:
    return sorted(re.findall(r"\d+", t.translate(_D)))


def smooth(text: str, lang: str, must_keep: list) -> Optional[str]:
    system = (
        f"Rewrite this spoken business briefing for a shopkeeper so it sounds natural and warm, in "
        f"{LANG_NAMES.get(lang, 'Hindi')}, in its native script, at most 60 words. Keep every number, "
        "name and amount EXACTLY as given. Do not add facts, advice or numbers. "
        'Output JSON only: {"text": "..."}.')
    data = chat_json(system, json.dumps({"text": text}, ensure_ascii=False), max_tokens=500)
    out = str(data.get("text", "")).strip()
    if not out or len(out) > len(text) * 1.4 + 40:
        return None
    if _nums(out) != _nums(text):
        return None
    if any(k and k not in out for k in must_keep):
        return None
    return out


def briefing(db, shop_id: int, now: Optional[datetime] = None, use_llm: bool = True) -> dict:
    now = now or clock.now()
    shop = db.get(Shop, shop_id)
    lang = shop.language
    d = gather(db, shop_id, now, lang)
    text = build_text(lang, shop.name, d)
    source = "template"
    if use_llm:
        keep = [shop.name] + d["low_names"] + ([d["tip"][1]] if d["tip"] else [])
        try:
            s = smooth(text, lang, keep)
            if s:
                text, source = s, "llm"
        except Exception:
            pass                                       # fail closed: keep the template text
    return {"text": text, "source": source, "lang": lang,
            "data": {**d, "tip": list(d["tip"]) if d["tip"] else None}}