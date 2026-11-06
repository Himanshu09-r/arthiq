"""Product-catalogue matching for spoken inventory commands."""
from dataclasses import dataclass, field
import re
import unicodedata

from rapidfuzz import fuzz
from sqlalchemy import select

from app.db.models import Item


def canon(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


@dataclass
class Candidate:
    item: Item


@dataclass
class Resolution:
    status: str  # match | ambiguous | maybe | none
    item: Item | None = None
    options: list[Candidate] = field(default_factory=list)


def resolve(db, shop_id: int, name: str) -> Resolution:
    query = canon(name)
    if not query:
        return Resolution("none")

    items = db.scalars(select(Item).where(
        Item.shop_id == shop_id,
        Item.status != "deleted"
    )).all()
    scored = []
    for item in items:
        names = [item.name, *(item.aliases or [])]
        normalized = [canon(n) for n in names if n]
        if query in normalized:
            return Resolution("match", item=item)
        score = max((max(fuzz.ratio(query, n), fuzz.token_set_ratio(query, n))
                     for n in normalized), default=0)
        if score >= 58:
            scored.append((score, item))

    scored.sort(key=lambda row: row[0], reverse=True)
    if not scored:
        return Resolution("none")
    top_score = scored[0][0]
    close = [item for score, item in scored if score >= max(58, top_score - 7)][:5]
    if top_score >= 90 and (len(scored) == 1 or top_score - scored[1][0] >= 8):
        return Resolution("match", item=scored[0][1])
    if len(close) > 1:
        return Resolution("ambiguous", options=[Candidate(item=x) for x in close])
    if top_score >= 72:
        return Resolution("maybe", options=[Candidate(item=scored[0][1])])
    return Resolution("none")
