"""Date resolution in plain code (never the LLM). Hindi / Hinglish / Marathi / Gujarati / English."""
import re
from datetime import datetime, timedelta
from typing import Optional

_DIGITS = str.maketrans("०१२३४५६७८९૦૧૨૩૪૫૬૭૮૯", "01234567890123456789")

WEEKDAYS = [  # Monday = 0
    ("monday", "somvar", "somwar", "सोमवार", "સોમવાર"),
    ("tuesday", "mangalvar", "mangalwar", "मंगलवार", "मंगळवार", "મંગળવાર"),
    ("wednesday", "budhvar", "budhwar", "बुधवार", "બુધવાર"),
    ("thursday", "guruvar", "guruwar", "veervar", "virvar", "brihaspativar", "गुरुवार", "वीरवार", "बृहस्पतिवार", "ગુરુવાર"),
    ("friday", "shukravar", "shukrawar", "शुक्रवार", "શુક્રવાર"),
    ("saturday", "shanivar", "shaniwar", "शनिवार", "શનિવાર"),
    ("sunday", "ravivar", "itwar", "itvar", "रविवार", "રવિવાર"),
]
TODAY = {"aaj", "आज", "today", "आजे", "આજે"}
TOMORROW = {"kal", "कल", "tomorrow", "उद्या", "કાલે"}
DAY_AFTER = {"parso", "parson", "परसों", "परसो", "परवा", "પરમદિવસે"}
WEEK_WORDS = {"hafte", "hafta", "हफ्ते", "हफ्ता", "week", "आठवड्यात", "અઠવાડિયે"}
TOD = {"subah": 11, "सुबह": 11, "सकाळी": 11, "dopahar": 14, "दोपहर": 14, "दुपारी": 14,
       "shaam": 18, "शाम": 18, "संध्याकाळी": 18, "raat": 20, "रात": 20, "रात्री": 20}
DEFAULT_HOUR = 18


def resolve_date(text: Optional[str], now: datetime) -> Optional[datetime]:
    if not text:
        return None
    t = text.lower().translate(_DIGITS)
    tokens = [x for x in re.split(r"[\s,.;:!?।\"'()\-/]+", t) if x]

    days = None
    m = re.search(r"(\d{1,3})\s*(?:din|दिन|divas|दिवस|days?|દિવસ)", t)
    if m:
        days = int(m.group(1))
    if days is None:
        for tok in tokens:
            if tok in TODAY:
                days = 0
                break
            if tok in TOMORROW:
                days = 1
                break
            if tok in DAY_AFTER:
                days = 2
                break
    if days is None:
        for tok in tokens:
            for wd, names in enumerate(WEEKDAYS):
                if any(tok.startswith(n) for n in names):
                    days = (wd - now.weekday()) % 7 or 7   # always a future day
                    break
            if days is not None:
                break
    if days is None and any(tok in WEEK_WORDS for tok in tokens):
        days = 7

    hour, minute, tod = None, 0, None
    m = re.search(r"(\d{1,2})(?::(\d{2}))?\s*(baje|bje|बजे|वाजता|વાગ્યે|am|pm)", t)
    if m:
        h, suffix = int(m.group(1)), m.group(3)
        minute = int(m.group(2) or 0)
        if suffix == "pm":
            h = h % 12 + 12
        elif suffix == "am":
            h = h % 12
        elif h <= 7:            # "2 baje" in a shop means 2 pm
            h += 12
        if 0 <= h <= 23 and 0 <= minute <= 59:
            hour = h
    for tok in tokens:
        if tok in TOD:
            tod = TOD[tok]
            break

    if days is None and hour is None and tod is None:
        return None
    if hour is None:
        hour = tod if tod is not None else DEFAULT_HOUR

    if days is None:            # only a time, e.g. "shaam ko" or "5 baje"
        cand = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        return cand if cand > now else cand + timedelta(days=1)
    target = (now + timedelta(days=days)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target