"""Deterministic Hindi/Hinglish/English parsing for frequent kirana commands."""
import re
from app.engine.units import canon_unit

_NUM_WORDS = {
    "ek": 1, "one": 1, "एक": 1, "do": 2, "two": 2, "दो": 2,
    "teen": 3, "three": 3, "तीन": 3, "char": 4, "chaar": 4, "four": 4, "चार": 4,
    "paanch": 5, "panch": 5, "five": 5, "पांच": 5, "पाँच": 5,
    "chhe": 6, "six": 6, "छह": 6, "saat": 7, "seven": 7, "सात": 7,
    "aath": 8, "eight": 8, "आठ": 8, "nau": 9, "nine": 9, "नौ": 9,
    "das": 10, "ten": 10, "दस": 10, "gyarah": 11, "eleven": 11, "ग्यारह": 11,
    "baarah": 12, "barah": 12, "twelve": 12, "बारह": 12,
    "aadha": 0.5, "half": 0.5, "आधा": 0.5, "pauna": 0.75, "पौना": 0.75,
}
_NUM_ALT = "|".join(re.escape(x) for x in sorted(_NUM_WORDS, key=len, reverse=True))
_NUM_RE = re.compile(rf"(?<![\w])(?P<num>\d+(?:\.\d+)?|{_NUM_ALT})(?![\w])", re.I)
_UNIT_WORDS = set("kilograms kilogram kilos kilo kgs kg किलोग्राम किलो grams grammes gramme gram gms gm g ग्राम millilitres milliliter milliliters millilitre ml मिलीलीटर मिली litres liters litre liter ltr lt l लीटर लिटर packets packet packs pack pkt पैकेट pieces piece pcs pc नग पीस टुकड़े टुकड़े dozens dozen दर्जन bottles bottle बोतल boxes box डिब्बे डिब्बा bags bag बोरी jar jars जार".split())
_UNIT_ALT = "|".join(re.escape(x) for x in sorted(_UNIT_WORDS, key=len, reverse=True))
_UNIT_RE = re.compile(rf"^\s*(?P<unit>{_UNIT_ALT})(?![\w])", re.I)
_UNIT_ANY_RE = re.compile(rf"(?<![\w])(?P<unit>{_UNIT_ALT})(?![\w])", re.I)
_STOCK_MARKER_RE = re.compile(r"\b(?:aa\s+gaya|aa\s+gaye|aa\s+gayi|aaya|aaye|aayi|mil\s+gaya|mil\s+gaye|receive(?:d)?|arrived|stock\s+in|add\s+stock|stock\s+mein\s+add|stock\s+me\s+add|goods\s+received|maal\s+aaya|samaan\s+aaya|saman\s+aaya)\b|आया|आयी|आए|आ गई|मिल गया|मिल गए|स्टॉक\s+में\s+जोड़|स्टॉक\s+में\s+डाल", re.I)
_STOCK_CONTEXT_RE = re.compile(r"\b(?:stock|inventory|goods|item|product|samaan|saman|maal|supply|shipment|delivery)\b|सामान|सामान\s+का|माल|स्टॉक|इन्वेंटरी|सप्लाई", re.I)

_SUMMARY_PATTERNS = [
    r"\baaj\s+(?:ki\s+)?(?:summary|report|hisab|hisaab|business|sale|sales|bikri|dhandha)\b",
    r"\baaj\s+ka\s+(?:(?:poora|pura|full|complete)\s+)?(?:hisab|hisaab|report|business|dhandha|collection)\b",
    r"\baaj\s+ki\s+(?:(?:poori|puri|full|complete)\s+)?(?:summary|report|hisab|hisaab)\b",
    r"\baaj\s+(?:kitni|kitna)\s+(?:sale|sales|bikri|collection|vasooli)\b",
    r"\baaj\s+kitne\s+(?:paise|rupaye)\s+(?:aaye|mile|collect)\b",
    r"\btoday(?:'s)?\s+(?:business\s+)?(?:summary|report|sales|collection|accounts?)\b",
    r"\b(?:daily|business)\s+(?:summary|report)\b",
    r"\bhow\s+much\s+(?:did\s+i\s+)?(?:sell|collect)\s+today\b",
    r"\bshow\s+(?:me\s+)?today(?:'s)?\s+(?:sales|business|summary|report)\b",
    r"\b(?:today|today's)\s+(?:sales|collection|accounts?|hisab|hisaab)\b",
    r"\bhow\s+was\s+(?:my\s+)?business\s+today\b",
    r"\bwhat\s+was\s+today's\s+(?:business|sale|sales)\b",
    r"आज\s*(?:की|का)?\s*(?:समरी|सारांश|रिपोर्ट|हिसाब|हिसाब-किताब|बिक्री|सेल|धंधा|कारोबार)",
    r"आज\s*(?:कितनी|कितना)\s*(?:बिक्री|सेल|कलेक्शन|वसूली)",
    r"आज\s*(?:का|की)\s*(?:हिसाब|बिजनेस|बिज़नेस|रिपोर्ट)",
]


def _quantity(value):
    token = str(value or "").strip().casefold()
    if token in _NUM_WORDS:
        return float(_NUM_WORDS[token])
    try:
        return float(token.replace(",", ""))
    except ValueError:
        return None


def is_daily_summary(text):
    value = str(text or "").casefold().strip()
    return any(re.search(p, value, re.I) for p in _SUMMARY_PATTERNS)


def _item_chunks(text):
    matches = list(_NUM_RE.finditer(text or ""))
    out = []
    for idx, match in enumerate(matches):
        qty = _quantity(match.group("num"))
        if qty is None or qty <= 0:
            continue
        rest = text[match.end():]
        unit_match = _UNIT_RE.match(rest)
        unit = canon_unit(unit_match.group("unit")) if unit_match else None
        start = match.end() + (unit_match.end() if unit_match else 0)
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        chunk = text[start:end]
        marker = _STOCK_MARKER_RE.search(chunk)
        if marker:
            chunk = chunk[:marker.start()]
        chunk = re.sub(r"\b(?:aur|and|plus|or)\b", " ", chunk, flags=re.I)
        chunk = re.sub(r"[,:;।.!?]+", " ", chunk)
        chunk = re.sub(r"\b(?:ka|ki|ke|of|the|item|product|samaan|saman|maal|stock|inventory)\b", " ", chunk, flags=re.I)
        # Supplier phrases belong to receipt metadata, not the product name.
        chunk = re.sub(r"\b(?:supplier|vendor|from)\b.*$", " ", chunk, flags=re.I)
        chunk = re.sub(r"\bse\s+[A-Za-z][A-Za-z .'-]{1,50}$", " ", chunk, flags=re.I)
        name = " ".join(chunk.split()).strip(" -")
        if name:
            out.append({"name": name, "qty": qty, "unit": unit, "price": None})
    return out


def _supplier(text):
    m = re.search(r"\b(?:supplier|vendor|from)\s+([A-Za-z][A-Za-z .'-]{1,50}?)(?=\s+(?:se|ne|ka|ki|for|received|aaya|aaye)\b|[,.;]|$)", text or "", re.I)
    return m.group(1).strip() if m else None


def parse_stock_in(text):
    value = str(text or "").strip()
    marker = _STOCK_MARKER_RE.search(value) or re.search(r"\b(?:stock\s+mein\s+add|add\s+(?:this\s+)?to\s+stock|inventory\s+received)\b", value, re.I)
    if not value or not marker:
        return None
    items = _item_chunks(value)
    # A bare statement such as "Ramesh aaya" is not an inventory receipt.
    # Accept an arrival verb without extracted quantities only when the speaker
    # explicitly refers to goods/stock; otherwise leave it to normal intent routing.
    if not items and not _STOCK_CONTEXT_RE.search(value):
        return None
    return {"items": items, "supplier": _supplier(value), "needs_items": not bool(items)}


def parse_stock_items(text):
    items = _item_chunks(str(text or "").strip())
    return {"items": items, "supplier": _supplier(text)} if items else None


def parse_single_quantity(text):
    value = str(text or "").strip()
    m = _NUM_RE.search(value)
    if not m:
        return None
    qty = _quantity(m.group("num"))
    if qty is None or qty <= 0:
        return None
    unit_m = _UNIT_RE.match(value[m.end():])
    unit = canon_unit(unit_m.group("unit")) if unit_m else None
    return qty, unit


def parse_new_product(text):
    value = str(text or "").strip()
    cancel = bool(re.search(r"\b(?:no|nahi|nahin|cancel|not\s+new|नहीं|नही|रद्द)\b", value, re.I))
    affirmative = bool(re.search(r"\b(?:yes|haan|han|ji|new|naya|nayi|नया|नई|हाँ|हां)\b", value, re.I))
    unit = None
    # The follow-up may be just "packet" / "bottle" rather than "1 packet".
    unit_m = _UNIT_ANY_RE.search(value)
    if unit_m:
        unit = canon_unit(unit_m.group("unit"))
    if unit is None:
        for m in _NUM_RE.finditer(value):
            unit_m = _UNIT_RE.match(value[m.end():])
            if unit_m:
                unit = canon_unit(unit_m.group("unit"))
                break
    price = None
    pm = re.search(r"(?:price|rate|selling|cost|rupees?|rs\.?|रुपये|रुपए|कीमत|भाव)\s*(?:is|hai|है|:|-)?\s*(\d{1,7})", value, re.I)
    if not pm:
        pm = re.search(r"(\d{1,7})\s*(?:rupees?|rs\.?|रुपये|रुपए|रु\.?)(?:\b|$)", value, re.I)
    if pm:
        price = int(pm.group(1))
    return {"cancel": cancel, "is_new": affirmative and not cancel, "unit": unit, "price": price}
