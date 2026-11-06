from dataclasses import dataclass, field
from typing import Optional
from app.db.models import Customer
from app.languages import SUPPORTED
from app.engine.customer_rules import normalize_phone, find_duplicates, DEFAULT_CREDIT_LIMIT


@dataclass
class RegCheck:
    status: str                              # ready | duplicate | error
    name: str = ""
    locality: Optional[str] = None
    phone: Optional[str] = None
    language: str = "hi-IN"
    credit_limit: int = DEFAULT_CREDIT_LIMIT
    duplicate: Optional[Customer] = None
    code: Optional[str] = None               # template key when status == error
    info: dict = field(default_factory=dict)


def _title(s) -> str:
    return " ".join(w.capitalize() for w in (s or "").replace(",", " ").split())


def check_registration(db, shop_id, name, locality, phone, language, credit_limit, shop_lang) -> RegCheck:
    name = _title(name)
    if len(name) < 2:
        return RegCheck("error", code="err_generic")
    ph = None
    if phone and str(phone).strip():
        ph = normalize_phone(phone)
        if not ph:
            return RegCheck("error", code="err_bad_phone")
    base = dict(
        name=name, locality=_title(locality) or None, phone=ph,
        language=language if language in SUPPORTED else shop_lang,
        credit_limit=credit_limit if isinstance(credit_limit, int) and 100 <= credit_limit <= 100000
        else DEFAULT_CREDIT_LIMIT)
    dups = find_duplicates(db, shop_id, name, base["locality"], ph)
    if dups:
        return RegCheck("duplicate", duplicate=dups[0], **base)
    return RegCheck("ready", **base)