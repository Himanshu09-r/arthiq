import re
from rapidfuzz import fuzz
from app.db.models import Customer, Item

_HONORIFICS = {"ji", "जी", "bhai", "भाई", "bhau", "भाऊ", "sahab", "साहब"}


def _norm(s: str) -> str:
    tokens = re.split(r"[\s,.;:!?।'\"-]+", (s or "").lower().strip())
    return " ".join(t for t in tokens if t and t not in _HONORIFICS)


def match_customer(db, shop_id: int, ref: str):
    """Returns ("ok"|"ambiguous"|"none", [customers])."""
    q = _norm(ref)
    if not q:
        return "none", []
    scored = []
    for c in db.query(Customer).filter_by(shop_id=shop_id).all():
        best = max(fuzz.ratio(q, _norm(n)) for n in [c.name, *c.nicknames])
        scored.append((best, c))
    scored.sort(key=lambda t: -t[0])
    if not scored or scored[0][0] < 80:
        return "none", []
    top = scored[0][0]
    close = [c for s, c in scored if s >= top - 5]
    return ("ok" if len(close) == 1 else "ambiguous"), close


def match_item(db, shop_id: int, name: str):
    q = _norm(name)
    if not q:
        return None
    best, found = 0, None
    for it in db.query(Item).filter_by(shop_id=shop_id).all():
        s = max(fuzz.ratio(q, _norm(n)) for n in [it.name, *it.aliases])
        if s > best:
            best, found = s, it
    return found if best >= 75 else None