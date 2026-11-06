"""Reminder writer: LLM draft -> safety filter -> fixed-template fallback. Amount always from code."""
import json
import re

from sqlalchemy import select

from app.agent.llm import LLMError, chat_json
from app.agent.safety import check_message
from app.db.models import Customer, Item
from app.engine.ladder import outstanding
from app.voice.templates_collect import LANG_NAMES, cx, lang_used

try:
    from app.voice.templates import item_label
except Exception:  # pragma: no cover
    item_label = None

TONE = {
    0: "a friendly nudge, the due date has arrived",
    3: "a gentle reminder that mentions the amount and the items in simple words",
    7: "polite, and offer that the customer can pay in two parts if that is easier",
    14: "a final polite reminder; say they can ignore it if already paid",
    "promise": "the customer promised to pay by a date that has passed; polite and calm, no pressure",
}


def tone_key(step: int):
    return "promise" if step >= 100 else step


def tpl_key(step: int) -> str:
    if step == 7:
        return "rem_split"
    if step == 14:
        return "rem_last"
    return "rem_gentle"


def items_summary(db, entry, lang: str) -> str:
    names = []
    for ln in (entry.items_json or []):
        try:
            if not isinstance(ln, dict):
                continue
            it = db.get(Item, ln["item_id"]) if ln.get("item_id") else None
            if it is not None and item_label is not None:
                names.append(item_label(it, lang))
            elif ln.get("name"):
                names.append(str(ln["name"]))
        except Exception:
            continue
    return ", ".join(names[:4])


def _template(db, shop, customer, entry, step, link, lang) -> str:
    items = items_summary(db, entry, lang_used(lang))
    text = cx(lang, tpl_key(step),
              cust=customer.name.split()[0], shop=shop.name, amount=outstanding(entry),
              items_part=f" ({items})" if items else "",
              pay_line=cx(lang, "pay_line", link=link) if link else "")
    return re.sub(r"\s+", " ", text).strip()


def write_reminder(db, shop, customer, entry, step: int, link, now) -> dict:
    lang = customer.preferred_language
    amount = outstanding(entry)
    others = db.scalars(select(Customer.name).where(
        Customer.shop_id == shop.id, Customer.id != customer.id)).all()
    facts = {
        "customer": customer.name.split()[0], "shop": shop.name, "amount": amount,
        "items": items_summary(db, entry, lang_used(lang)), "link": link or "",
        "language": LANG_NAMES.get(lang, "Hindi"), "tone": TONE[tone_key(step)],
    }
    system = (
        "You write one short WhatsApp message from an Indian kirana shop to a customer who owes money. "
        'Output JSON only: {"message": "..."}. '
        f"Write in {facts['language']}, in its native script (names and the link stay as given). "
        "Rules: warm, polite, respectful, at most 3 short sentences. Include the shop name, the customer's name, "
        "the exact amount with the ₹ sign, and the items if given. Include the payment link exactly as given, once. "
        "Never threaten, never shame, never mention other people, never mention interest, fees or penalties, "
        f"never invent facts or dates. Tone for this message: {facts['tone']}."
    )
    reason = "llm_error"
    try:
        data = chat_json(system, json.dumps(facts, ensure_ascii=False), max_tokens=500)
        text = str(data.get("message", "")).strip()
        ok, reason = check_message(text, amount=amount, link=link or None, own_name=customer.name,
                                   shop_name=shop.name, other_names=others)
        if ok:
            return {"text": text, "source": "llm", "reason": "ok"}
    except (LLMError, Exception) as e:  # fail closed -> template
        reason = f"llm_error:{type(e).__name__}"
    return {"text": _template(db, shop, customer, entry, step, link, lang),
            "source": "template", "reason": reason}