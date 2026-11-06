"""Customer reply classifier. Rules first for safety-critical 'stop'; LLM for the rest; keyword fallback."""
from datetime import datetime
from typing import Optional

from app.agent.llm import chat_json
from app.engine import clock
from app.voice.dates import resolve_date

STOP_WORDS = ["stop", "unsubscribe", "band karo", "mat bhej", "message mat", "do not message",
              "don't message", "dont message", "बंद करो", "मत भेज", "मैसेज मत", "थांबवा", "નહીં મોકલો", "બંધ કરો"]
DISPUTE_WORDS = ["galat", "nahi liya", "nahi li thi", "jhoot", "wrong", "never took", "disagree",
                 "गलत", "नहीं लिया", "झूठ", "चुकीचे", "ખોટું"]
LABELS = {"paid", "promise", "time", "dispute", "other"}

SYSTEM = (
    "You classify a customer's WhatsApp reply to a payment reminder from a kirana shop. "
    "The reply may be Hindi, Hinglish, English, Marathi or Gujarati. "
    'Return JSON only: {"label": "paid|promise|time|dispute|other", "date_text": "..."}. '
    "paid = customer says they already paid or sent the money. "
    "promise = customer says they will pay on a specific day or time. "
    "time = customer asks for more time without naming a day. "
    "dispute = customer says the amount or purchase is wrong or they never took it. "
    "other = anything else. "
    "date_text = the words naming the promised day or time, copied exactly from the reply, else empty."
)


def classify(text: str, now: Optional[datetime] = None) -> dict:
    now = now or clock.now()
    low = (text or "").lower()
    if any(w in low for w in STOP_WORDS):
        return {"label": "stop", "date_text": "", "source": "rule"}
    try:
        data = chat_json(SYSTEM, text, max_tokens=200)
        label = str(data.get("label", "other")).strip().lower()
        if label not in LABELS:
            label = "other"
        return {"label": label, "date_text": str(data.get("date_text", "") or ""), "source": "llm"}
    except Exception:
        if any(w in low for w in DISPUTE_WORDS):
            return {"label": "dispute", "date_text": "", "source": "fallback"}
        if resolve_date(text, now) is not None:
            return {"label": "promise", "date_text": text, "source": "fallback"}
        return {"label": "other", "date_text": "", "source": "fallback"}