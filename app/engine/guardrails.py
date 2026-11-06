"""Guardrail engine: plain Python rules, no LLM. Output: allow | delay | block + reason."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy import select, func

from app.db.models import ActionAudit, Commitment, Reminder

WEEKLY_CAP = 3  # max reminders per customer in any 7 days


@dataclass
class Decision:
    verdict: str            # allow | delay | block
    reason: str
    resume_at: Optional[datetime] = None

    @property
    def allowed(self) -> bool:
        return self.verdict == "allow"


def in_quiet_hours(hour: int, start: int, end: int) -> bool:
    if start == end:
        return False
    if start > end:                      # wraps midnight, e.g. 20 -> 9
        return hour >= start or hour < end
    return start <= hour < end


def next_quiet_end(now: datetime, end: int) -> datetime:
    candidate = now.replace(hour=end, minute=0, second=0, microsecond=0)
    if candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def late_fee_allowed(shop) -> bool:
    # No interest or late fee unless the shopkeeper switched it on.
    # (Tracking that the customer was told is planned.)
    return bool(shop.late_fee_enabled)


def check_reminder(db, shop, customer, entry, channel: str, now: datetime) -> Decision:
    # ---- hard blocks first ----
    if entry.status == "PAID" or (entry.amount - entry.paid_amount) <= 0:
        return Decision("block", "already_paid")
    if entry.status == "DISPUTED":
        return Decision("block", "open_dispute")
    disputed = db.scalar(
        select(func.count(Commitment.id)).where(
            Commitment.customer_id == customer.id, Commitment.state == "DISPUTED"))
    if disputed:
        return Decision("block", "open_dispute")
    if customer.paused:
        return Decision("block", "customer_paused")
    if not customer.message_opt_in:
        return Decision("block", "no_opt_in")
    if channel == "voice" and not shop.calls_allowed:
        return Decision("block", "calls_not_allowed")

    # ---- delays ----
    if in_quiet_hours(now.hour, shop.quiet_start_hour, shop.quiet_end_hour):
        return Decision("delay", "quiet_hours", next_quiet_end(now, shop.quiet_end_hour))

    cutoff = now - timedelta(days=7)
    times = sorted(db.scalars(
        select(Reminder.created_at).where(
            Reminder.customer_id == customer.id,
            Reminder.status.in_(["READY", "SENT"]),
            Reminder.created_at > cutoff)).all())
    if len(times) >= WEEKLY_CAP:
        return Decision("delay", "weekly_cap", times[len(times) - WEEKLY_CAP] + timedelta(days=7))

    return Decision("allow", "ok")


def log_decision(db, shop_id: int, customer, entry, step: int, channel: str,
                 decision: Decision, now: datetime) -> None:
    db.add(ActionAudit(
        shop_id=shop_id,
        actor="guardrail",
        tool="reminder_check",
        arguments={
            "entry_id": entry.id, "customer_id": customer.id,
            "step": step, "channel": channel,
            "resume_at": decision.resume_at.isoformat() if decision.resume_at else None,
        },
        rule_decision=f"{decision.verdict}:{decision.reason}",
        timestamp=now,
    ))