"""Demo clock. Use clock.now() everywhere in collection code, never datetime.now().
advance() fast-forwards time so the reminder ladder can be shown in seconds."""
from datetime import datetime, timedelta

_offset = timedelta(0)


def now() -> datetime:
    return datetime.now() + _offset


def advance(days: int = 0, hours: int = 0) -> datetime:
    global _offset
    _offset += timedelta(days=days, hours=hours)
    return now()


def reset() -> None:
    global _offset
    _offset = timedelta(0)


def offset_days() -> float:
    return _offset.total_seconds() / 86400