"""Conservative quantity/unit normalisation for stock-in commands."""
from dataclasses import dataclass
import re
import unicodedata

_ALIASES = {
    "kg": {"kg", "kgs", "kilo", "kilos", "kilogram", "kilograms", "kilogramme", "किलो", "किलोग्राम", "किलो그램"},
    "g": {"g", "gm", "gms", "gram", "grams", "gramme", "grammes", "ग्राम"},
    "litre": {"l", "lt", "ltr", "litre", "litres", "liter", "liters", "लीटर", "लिटर"},
    "ml": {"ml", "millilitre", "millilitres", "milliliter", "milliliters", "मिलीलीटर", "मिली"},
    "piece": {"pc", "pcs", "piece", "pieces", "unit", "units", "नग", "पीस", "टुकड़ा", "टुकड़े"},
    "packet": {"pkt", "pack", "packet", "packets", "पैकेट"},
    "dozen": {"dozen", "dozens", "दर्जन"},
    "bottle": {"bottle", "bottles", "बोतल"},
    "box": {"box", "boxes", "डिब्बा", "डिब्बे"},
    "bag": {"bag", "bags", "बोरी", "थैला"},
    "jar": {"jar", "jars", "जार"},
}

_LOOKUP = {alias.casefold(): canonical for canonical, aliases in _ALIASES.items() for alias in aliases}


def _norm(s):
    s = unicodedata.normalize("NFKC", str(s or "")).casefold().strip()
    return re.sub(r"\s+", " ", s)


def canon_unit(unit):
    if unit is None or not str(unit).strip():
        return None
    key = _norm(unit).rstrip(".,")
    return _LOOKUP.get(key, key if key in _ALIASES else None)


def family(unit):
    u = canon_unit(unit) or _norm(unit)
    if u in ("kg", "g"):
        return "mass"
    if u in ("litre", "ml"):
        return "volume"
    if u in ("piece", "dozen", "packet", "bottle", "box", "bag", "jar"):
        return "count"
    return u or None


@dataclass
class Converted:
    ok: bool
    qty: float = 0.0
    approximate: bool = False
    reason: str | None = None


def convert(qty, spoken_unit, item):
    """Convert a spoken quantity into the catalogue item's unit. No cross-family guesses."""
    target = canon_unit(getattr(item, "unit", None)) or _norm(getattr(item, "unit", ""))
    source = canon_unit(spoken_unit) if spoken_unit else target
    if not target:
        return Converted(False, reason="unknown_unit")
    if source is None:
        return Converted(False, reason="unknown_unit")
    q = float(qty)
    if q <= 0:
        return Converted(False, reason="bad_quantity")
    if source == target:
        return Converted(True, round(q, 4))
    scales = {
        ("g", "kg"): 0.001,
        ("kg", "g"): 1000.0,
        ("ml", "litre"): 0.001,
        ("litre", "ml"): 1000.0,
        ("dozen", "piece"): 12.0,
        ("piece", "dozen"): 1.0 / 12.0,
    }
    factor = scales.get((source, target))
    if factor is not None:
        # These conversions are exact scale changes, not estimates.
        return Converted(True, round(q * factor, 4), approximate=False)
    # A dozen can reasonably be represented as 12 packets/bottles/pieces only when
    # the catalogue tracks individual countable units. Never convert weight/volume.
    if source == "dozen" and family(target) == "count":
        return Converted(True, round(q * 12.0, 4), approximate=False)
    if family(source) == family(target):
        # Count units such as packet and box are not interchangeable.
        return Converted(False, reason="unit_mismatch")
    return Converted(False, reason="unit_mismatch")
