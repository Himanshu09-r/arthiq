"""Wake phrases: "Suno ARTIQ", "ARTIQ suno", "Hey ARTIQ" (Roman or Indic script, fuzzy).
Speech-to-text often writes the brand as Aarti / Arthik / आरती / आर्थिक, so those count too.
A bare brand word is not enough: it must come with suno / hey, so normal talk never triggers it."""
import re
try:
    from rapidfuzz import fuzz
    def _sim(a, b): return fuzz.ratio(a, b)
except ImportError:                                  # rapidfuzz is a project dependency; this is a safety net
    from difflib import SequenceMatcher
    def _sim(a, b): return 100 * SequenceMatcher(None, a, b).ratio()

BRAND = ["arthiq", "arthik", "artiq", "artik", "artic", "arthic", "arthek", "artheek", "aarthik", "arti", "aarti", "arthi",
         "arth iq", "arth ik", "art iq", "art hiq", "ar tiq",
         "अर्थिक", "आर्थिक", "अर्थिक्यू", "आर्टिक", "आर्टिक्यू", "अर्टिक", "आर्तिक", "अर्तिक", "आरती", "आर्ती", "अर्ती", "आर्थी",
         "अर्थ आईक्यू", "अर्थ आइक्यू", "अर्थ इक", "आर्ट आईक्यू", "आर्ट इक"]
CALL = ["suno", "sunno", "sunao", "suniye", "suniye", "सुनो", "सुनौ", "सुन्नो", "सुनिए", "सुनिये", "सुनाओ", "सुन"]
GREET = ["hey", "hay", "hi", "hello", "hallo", "ok", "okay", "oye", "अरे", "हे", "हेय", "हाय", "हेलो", "हैलो", "ओए", "ए"]
_TOKEN = re.compile(r"[^\s,.;:!?\"'()\-–—।|]+")


def _fuzzy(tok, words):
    if len(tok) <= 2:                                 # very short tokens must match exactly
        return tok in words
    return any(_sim(tok, w) >= 82 for w in words)


def _is_brand(s):
    if len(s) <= 4:
        return s in BRAND
    return any(_sim(s, b) >= 82 and abs(len(s) - len(b)) <= 1 for b in BRAND)   # "article" must not pass for "artic"


def detect(transcript: str):
    """-> (matched, command). `command` = what was said after the last wake phrase ('' if nothing)."""
    text = transcript or ""
    toks = [(m.group().lower(), m.end()) for m in _TOKEN.finditer(text)]
    n, end = len(toks), None

    def hit(pos):
        nonlocal end
        end = pos if end is None else max(end, pos)

    for i in range(n):
        for L in (1, 2):                              # brand may be split into two words: "arth iq"
            if i + L > n:
                continue
            cand = [t for t, _ in toks[i:i + L]]
            # A following quantity like "1 kg" must not be absorbed into a fuzzy
            # split-brand match ("arthiq 1" is deceptively close to "arthiq").
            if L == 2 and any(any(ch.isdigit() for ch in token) for token in cand):
                continue
            if not (_is_brand(" ".join(cand)) or _is_brand("".join(cand))):
                continue
            j = i + L - 1
            if i > 0 and (_fuzzy(toks[i - 1][0], CALL) or _fuzzy(toks[i - 1][0], GREET)):
                hit(toks[j][1])                       # "suno artiq" / "hey artiq"
            if j + 1 < n and _fuzzy(toks[j + 1][0], CALL):
                hit(toks[j + 1][1])                   # "artiq suno"
        tok = toks[i][0]
        for word in CALL + GREET:                     # one glued token: "artiqsuno", "heyartiq"
            if len(word) > 2 and len(tok) > len(word) + 2:
                if (tok.endswith(word) and _is_brand(tok[:-len(word)])) or (tok.startswith(word) and _is_brand(tok[len(word):])):
                    hit(toks[i][1])
    if end is None:
        return False, ""
    return True, text[end:].strip(" ,.-।!?")
