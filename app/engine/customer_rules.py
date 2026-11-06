import unicodedata
from typing import Optional
from rapidfuzz import fuzz
from app.db.models import Customer
from app.engine.matching import _norm

DEFAULT_CREDIT_LIMIT = 2000


def display_name(c) -> str:
    """'Aryan Chouhan, Patel Nagar' (spoken and shown when names clash)."""
    loc = getattr(c, "locality", None)
    return f"{c.name}, {loc}" if loc else c.name


def normalize_phone(raw) -> Optional[str]:
    """Indian mobile: 10 digits starting 6-9. Accepts +91, leading 0, spaces, Devanagari digits."""
    if not raw:
        return None
    digits = "".join(str(unicodedata.decimal(ch)) for ch in str(raw) if ch.isdecimal())
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return digits if len(digits) == 10 and digits[0] in "6789" else None


def find_duplicates(db, shop_id: int, name: str, locality: Optional[str], phone: Optional[str]):
    """Same phone, or a near-identical name in the same (or unknown) locality."""
    q, loc = _norm(name), _norm(locality or "")
    found = []
    for c in db.query(Customer).filter_by(shop_id=shop_id).all():
        same_phone = bool(phone) and normalize_phone(c.phone) == phone
        c_loc = _norm(getattr(c, "locality", None) or "")
        same_place = (not loc) or (not c_loc) or fuzz.ratio(loc, c_loc) >= 80
        if same_phone or (fuzz.ratio(q, _norm(c.name)) >= 88 and same_place):
            found.append(c)
    return found