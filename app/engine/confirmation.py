"""Spoken confirmation engine: classify the reply, expire stale confirmations."""
import os
import time
from dataclasses import dataclass, field

from app.voice.confirm_vocab import tokens, vocab_for, BUT

TTL = int(os.getenv("CONFIRM_TTL_SECONDS", "120"))   # seconds a confirmation stays valid


@dataclass
class Reply:
    kind: str                    # yes | no | correction | other | empty
    has_yes: bool
    has_no: bool
    content: list = field(default_factory=list)


def _score(toks, v):
    y = any(t in v.yes for t in toks)
    n = any(t in v.no for t in toks)
    w = any(t in v.weak for t in toks)
    content = [t for t in toks
               if t not in v.yes and t not in v.no and t not in v.weak and t not in v.filler]
    return y, n, w, content


def classify(text: str, lang=None) -> Reply:
    toks = tokens(text)
    if not toks:
        return Reply("empty", False, False, [])
    y, n, w, content = _score(toks, vocab_for(lang))
    if not (y or n or w) and lang is not None:       # answered in another language: accept it
        y2, n2, w2, c2 = _score(toks, vocab_for(None))
        if y2 or n2 or w2:
            y, n, w, content = y2, n2, w2, c2
    numeric = any(any(ch.isdigit() for ch in t) for t in content)
    but = any(t in BUT for t in toks)
    clean = len(content) <= 1 and not numeric and not but
    if n:
        kind = "no" if clean else "correction"
    elif y:
        kind = "yes" if clean else "correction"
    elif w and not content and not but:
        kind, y = "yes", True
    else:
        kind = "other"
    return Reply(kind, y, n, content)


# ---- state helpers (timestamps live inside the session dicts as "_t") ----
def _expired(d) -> bool:
    t = d.get("_t")
    return t is not None and (time.monotonic() - t) > TTL


def expire_stale(s):
    """Drops expired follow-up contexts. Returns the expired pending dict (or None)."""
    for name in ("awaiting", "duplicate", "followup", "stock_ask"):
        d = getattr(s, name, None)
        if isinstance(d, dict) and _expired(d):
            setattr(s, name, None)
    p = s.pending
    if isinstance(p, dict) and _expired(p):
        s.pending = None
        return p
    return None


def stamp(s):
    now = time.monotonic()
    for name in ("pending", "awaiting", "duplicate", "followup", "stock_ask"):
        d = getattr(s, name, None)
        if isinstance(d, dict):
            d.setdefault("_t", now)