"""Safety filter for LLM-written customer messages. Plain rules. Fails closed."""
import re

BLOCK = [
    "police", "pulis", "court", "legal action", "lawyer", "fir ", "jail", "threat", "shame",
    "embarrass", "everyone will know", "sab ko bata", "badnam", "mohalle", "neighbour", "neighbor",
    "late fee", "interest", "penalty", "jurmana", "byaj",
    "पुलिस", "कोर्ट", "वकील", "जेल", "बदनाम", "शर्म", "धमकी", "मोहल्ले", "पड़ोस", "ब्याज",
    "जुर्माना", "पेनल्टी", "कानूनी", "पोलीस", "व्याज", "दंड", "શરમ", "બદનામ", "પોલીસ", "કોર્ટ", "વ્યાજ", "દંડ",
]
URL_RE = re.compile(r"https?://[A-Za-z0-9._~:/?#@!$&*+,;=%-]+")
_D = str.maketrans("०१२३४५६७८९૦૧૨૩૪૫૬૭૮૯", "01234567890123456789")
MAX_LEN = 420


def _tokens(name: str) -> set:
    return {t for t in re.split(r"[^\w]+", (name or "").lower()) if len(t) >= 3}


def check_message(text, *, amount, link, own_name, shop_name, other_names):
    if not text or not text.strip():
        return False, "empty"
    if len(text) > MAX_LEN:
        return False, "too_long"
    low = text.lower()
    for w in BLOCK:
        if w in low:
            return False, f"blocked_word:{w.strip()}"
    if str(amount) not in low.translate(_D).replace(",", ""):
        return False, "amount_missing"
    if link and link not in text:
        return False, "link_missing"
    urls = {u.rstrip(".,") for u in URL_RE.findall(text)}
    allowed = {link.rstrip(".,")} if link else set()
    if urls - allowed:
        return False, "foreign_url"
    safe = _tokens(own_name) | _tokens(shop_name)
    for n in other_names:
        for tok in _tokens(n):
            if len(tok) < 4 or tok in safe:
                continue
            if re.search(rf"\b{re.escape(tok)}\b", low):
                return False, "mentions_other"
    return True, "ok"